from django.shortcuts import render, redirect
from django.http import HttpRequest, JsonResponse
from django.utils import timezone
from django.urls import reverse
from web.providers import ProviderError, get_experiment_from_provider
from web.models import *
from common import TaskQueues, get_object_store
import functools
from hashlib import sha256
import logging
import mimetypes
import os
from common.shortid import MultiShortIDs
from werkzeug.contrib.fixers import ProxyFix
from werkzeug.utils import secure_filename


#short_ids = MultiShortIDs(os.environ['SHORTIDS_SALT'])


# Middleware allowing this to be run behind a reverse proxy
if 'WEB_BEHIND_PROXY' in os.environ:
    # Use ProxyFix to fix the remote address, HTTP host and HTTP scheme
    app.wsgi_app = ProxyFix(app.wsgi_app)
    
    # Fix SCRIPT_NAME to allow the app to run under a subdirectory
    old_app = app.wsgi_app
    
    def wsgi_app(environ, start_response):
        script_name = environ.get('HTTP_X_SCRIPT_NAME', '')
        if script_name:
            environ['SCRIPT_NAME'] = script_name
            path_info = environ['PATH_INFO']
            if path_info.startswith(script_name):
                environ['PATH_INFO'] = path_info[len(script_name):]

        scheme = environ.get('HTTP_X_SCHEME', '')
        if scheme:
            environ['wsgi.url_scheme'] = scheme
        return old_app(environ, start_response)

    app.wsgi_app = wsgi_app


## SQL database
#engine, SQLSession = database.connect()
#
#if not engine.dialect.has_table(engine.connect(), 'experiments'):
#    logging.warning("The tables don't seem to exist; creating")
#    from common.database import Base
#
#    Base.metadata.create_all(bind=engine)


# AMQP
tasks = TaskQueues()


# Object storage
#object_store = get_object_store()

#object_store.create_buckets()


def sql_session(func):
    def wrapper(**kwargs):
        session = SQLSession()
        flask.g.sql_session = session
        try:
            return func(session=session, **kwargs)
        finally:
            flask.g.sql_session = None
            session.close()
    functools.update_wrapper(wrapper, func)
    return wrapper


def index(request):
    return render(request,'index.html',{})

def about(request):
    return render(request,'about.html',{})

def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip

def unpack(request):
    """Target of the landing page.
        
        An experiment has been provided, store it and start the build process.
        """
    # Get uploaded file
    uploaded_file = request.FILES['rpz_file']
    assert uploaded_file.name
    # app.logger.info("Incoming file: %r", uploaded_file.filename)
    filename = secure_filename(uploaded_file.name)
    
    # Hash it
    hasher = sha256()
    chunk = uploaded_file.read(4096)
    while chunk:
        hasher.update(chunk)
        chunk = uploaded_file.read(4096)
    filehash = hasher.hexdigest()
    # app.logger.info("Computed hash: %s", filehash)

    # Rewind it
    uploaded_file.seek(0, 0)
    
    # Check for existence of experiment
    experiment = Experiment(hash = filehash)
    if experiment:
        experiment.last_access = timezone.now()
        # app.logger.info("File exists in storage")
    else:
        # Insert it on S3
        # object_store.upload_fileobj('experiments', filehash, uploaded_file)
        # app.logger.info("Inserted file in storage")
        
        # Insert it in database
        experiment = Experiment(hash=filehash)

    experiment.save()

    # Insert Upload in database
    upload = Upload(experiment_hash=experiment,filename=filename,submitted_ip=get_client_ip(request))
    upload.save()

    # Encode ID for permanent URL
    upload_short_id = upload.short_id
        
    # Redirect to build page
    return redirect(reverse('reproduce_local', kwargs={'upload_short_id': upload_short_id}), 302)

def reproduce_local(request, upload_short_id):
    """Show build log and ask for run parameters.
    """
    # Decode info from URL
    # app.logger.info("Decoding %r", upload_short_id)
    try:
        short_ids = MultiShortIDs(os.environ['SHORTIDS_SALT'])
        upload_id = short_ids.decode('upload', upload_short_id)
    except ValueError:
        return render(request, 'setup_notfound.html')

    print(upload_id)
    # Look up the experiment in database
    upload = Upload.objects.filter(id=upload_id)
    if not upload:
        return render(request, 'setup_notfound.html')

    # Also updates last access
    experiment = Experiment(hash = upload.experiment_hash)
    if experiment:
        experiment.last_access = timezone.now()
        experiment.save()

    return reproduce_common(upload, request)

def reproduce_provider(request, provider, provider_path):
    """Reproduce an experiment from a data repository (provider).
        """
    # Check the database for an experiment already stored matching the URI
    provider_key = '%s/%s' % (provider, provider_path)
                
    # Get the first row returned
    query = Upload.objects.filter(provider_key=provider_key).order_by('id')
    upload = query.first()
    print(upload)
    
    
    if not upload:
        try:
            upload = get_experiment_from_provider(request, get_client_ip(request), provider, provider_path)
        except ProviderError as e:
            return render('setup_notfound.html',message=e.message), 404

    # Also updates last access
    exp = Experiment(hash = upload.experiment_hash)
    exp.last_access = timezone.now()
    exp.save()

    return reproduce_common(upload, request)

def url_for_upload(upload):
    if upload.provider_key is not None:
        provider, path = upload.provider_key.split('/', 1)
        return reverse('reproduce_provider',
                       kwargs={'provider':provider, 'provider_path':path})
    else:
        return reverse('reproduce_local', kwargs={'upload_short_id':upload.short_id})

def reproduce_common(upload, request):
    experiment = Experiment.objects.filter(hash = upload.experiment_hash)[0]
    filename = upload.filename
    experiment_url = url_for_upload(upload)

    # JSON endpoint, returns data for JavaScript to update the page
    if (request.META.get('CONTENT_TYPE') == 'application/json'):
        log_from = int(request.args.get('log_from', '0'), 10)
        return JsonResponse({'status': experiment.status.name,'log': experiment.get_log(log_from),
                        'params': [
                                    {'name': p.name, 'optional': p.optional,
                                    'default': p.default}
                                    for p in experiment.parameters]})
    # HTML view, return the page
    else:
        # If it's done building, send build log and run form
        if experiment.status == '4':
            # app.logger.info("Experiment already built")
            input_files = (Path.objects
                        .filter(experiment_hash = experiment.hash)
                        .filter(is_input = True)).all()

            respParams = dict()
            respParams['filename'] = filename
            respParams['built'] = True
            respParams['error'] = False
            respParams['log'] = experiment.get_log(0)
            respParams['params'] = experiment.parameters
            respParams['input_files'] = input_files
            respParams['upload_short_id'] = upload.short_id
            respParams['experiment_url'] = experiment_url

            return render(request, 'setup.html', respParams)

        if experiment.status == '0':
            # app.logger.info("Experiment is errored")

            respParams = dict()
            respParams['filename'] = filename
            respParams['built'] = True
            respParams['error'] = False
            respParams['log'] = experiment.get_log(0)
            respParams['upload_short_id'] = upload.short_id
            respParams['experiment_url'] = experiment_url

            return render(request, 'setup.html', respParams)

        # If it's currently building, show the log
        elif experiment.status == '3':
            # app.logger.info("Experiment is currently building")

            respParams = dict()
            respParams['filename'] = filename
            respParams['built'] = True
            respParams['log'] = experiment.get_log(0)
            respParams['upload_short_id'] = upload.short_id
            respParams['experiment_url'] = experiment_url

            return render(request, 'setup.html', respParams)

        # Else, trigger the build
        else:
            if experiment.status == '1':
                # app.logger.info("Triggering a build, sending message")
                experiment.status = '2'
                # Need to have someone initialize the TasQueues to initaite the RabbitMQ Channel
                # tasks.publish_build_task(experiment.hash)

                respParams = dict()
                respParams['filename'] = filename
                respParams['built'] = True
                respParams['upload_short_id'] = upload.id
                respParams['experiment_url'] = experiment_url

                return render(request, 'setup.html', respParams)


def start_run(upload_short_id, request):
    """Gets the run parameters POSTed to from /reproduce.
    Triggers the run and redirects to the results page.
    """
    # Decode info from URL
    # app.logger.info("Decoding %r", upload_short_id)
    try:
        upload_id = short_ids.decode('upload', upload_short_id)
    except ValueError:
        return render_template('setup_notfound.html'), 404

    # Look up the experiment in database
    upload = (session.query(database.Upload)
              .options(joinedload(database.Upload.experiment))
              .get(upload_id))
    if not upload:
        return render_template('setup_notfound.html'), 404
    experiment = upload.experiment

    # New run entry
    try:
        run = database.Run(experiment_hash=experiment.hash,
                           upload_id=upload_id)
        session.add(run)

        # Get list of parameters
        params = set()
        params_unset = set()
        for param in experiment.parameters:
            if not param.optional:
                params_unset.add(param.name)
            params.add(param.name)

        # Get run parameters
        for k, v in request.form.iteritems():
            if k.startswith('param_'):
                name = k[6:]
                if name not in params:
                    raise ValueError("Unknown parameter %s" % k)
                run.parameter_values.append(database.ParameterValue(name=name,
                                                                    value=v))
                params_unset.discard(name)

        if params_unset:
            raise ValueError("Missing value for parameters: %s" %
                             ", ".join(params_unset))

        # Get list of input files
        input_files = set(
            p.name for p in (
                session.query(database.Path)
                .filter(database.Path.experiment_hash == experiment.hash)
                .filter(database.Path.is_input).all()))

        # Get input files
        for k, uploaded_file in request.files.iteritems():
            if not uploaded_file:
                continue

            if not k.startswith('inputfile_') or k[10:] not in input_files:
                raise ValueError("Unknown input file %s" % k)

            name = k[10:]
            app.logger.info("Incoming input file: %s", name)

            # Hash file
            hasher = sha256()
            chunk = uploaded_file.read(4096)
            while chunk:
                hasher.update(chunk)
                chunk = uploaded_file.read(4096)
            inputfilehash = hasher.hexdigest()
            app.logger.info("Computed hash: %s", inputfilehash)

            # Rewind it
            filesize = uploaded_file.tell()
            uploaded_file.seek(0, 0)

            # Insert it on S3
            object_store.upload_fileobj('inputs', inputfilehash, uploaded_file)
            app.logger.info("Inserted file in storage")

            # Insert it in database
            input_file = database.InputFile(hash=inputfilehash, name=name,
                                            size=filesize)
            run.input_files.append(input_file)

        # Trigger run
        session.commit()
        tasks.publish_run_task(str(run.id))

        # Redirect to results page
        return redirect(url_for('results', run_short_id=run.short_id), 302)
    except Exception:
        session.rollback()
        raise


