from django.shortcuts import render
from web.providers import ProviderError, get_experiment_from_provider
from common import TaskQueues, get_object_store
import functools
from hashlib import sha256
import logging
import mimetypes
import os
from common.shortid import MultiShortIDs


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

def unpack(session):
    """Target of the landing page.
        
        An experiment has been provided, store it and start the build process.
        """
    # Get uploaded file
    uploaded_file = request.files['rpz_file']
    assert uploaded_file.filename
    app.logger.info("Incoming file: %r", uploaded_file.filename)
    filename = secure_filename(uploaded_file.filename)
    
    # Hash it
    hasher = sha256()
    chunk = uploaded_file.read(4096)
    while chunk:
        hasher.update(chunk)
        chunk = uploaded_file.read(4096)
    filehash = hasher.hexdigest()
    app.logger.info("Computed hash: %s", filehash)

    # Rewind it
    uploaded_file.seek(0, 0)
    
    # Check for existence of experiment
    experiment = session.query(database.Experiment).get(filehash)
    if experiment:
        experiment.last_access = functions.now()
        app.logger.info("File exists in storage")
    else:
        # Insert it on S3
        object_store.upload_fileobj('experiments', filehash, uploaded_file)
        app.logger.info("Inserted file in storage")
        
        # Insert it in database
        experiment = database.Experiment(hash=filehash)
        session.add(experiment)

    # Insert Upload in database
    upload = database.Upload(experiment=experiment,filename=filename,submitted_ip=request.remote_addr)
    session.add(upload)
    session.commit()

    # Encode ID for permanent URL
    upload_short_id = upload.short_id
        
    # Redirect to build page
    return redirect(url_for('reproduce_local',upload_short_id=upload_short_id), 302)


def reproduce_provider(session,provider, provider_path):
    """Reproduce an experiment from a data repository (provider).
        """
    # Check the database for an experiment already stored matching the URI
    provider_key = '%s/%s' % (provider, provider_path)
    upload = (session.query(database.Upload)
              .options(joinedload(database.Upload.experiment))
              .filter(database.Upload.provider_key == provider_key)
              .order_by(database.Upload.id.desc())).first()
    if not upload:
        try:
            upload = get_experiment_from_provider(session, request.remote_addr,provider, provider_path)
        except ProviderError as e:
            return render_template('setup_notfound.html',message=e.message), 404

    # Also updates last access
    upload.experiment.last_access = functions.now()
    return reproduce_common(upload, session)

def reproduce_common(upload, session):
    experiment = upload.experiment
    filename = upload.filename
    experiment_url = url_for_upload(upload)
    try:
        # JSON endpoint, returns data for JavaScript to update the page
        if (request.accept_mimetypes.best_match(['application/json','text/html']) =='application/json'):
            log_from = int(request.args.get('log_from', '0'), 10)
            return jsonify({'status': experiment.status.name,'log': experiment.get_log(log_from),
                           'params': [
                                      {'name': p.name, 'optional': p.optional,
                                      'default': p.default}
                                      for p in experiment.parameters]})
            # HTML view, return the page
        else:
            # If it's done building, send build log and run form
            if experiment.status == database.Status.BUILT:
                app.logger.info("Experiment already built")
                input_files = (session.query(database.Path)
                               .filter(database.Path.experiment_hash == experiment.hash)
                               .filter(database.Path.is_input)).all()
                return render_template('setup.html', filename=filename,
                                                      built=True, error=False,
                                                      log=experiment.get_log(0),
                                                      params=experiment.parameters,
                                                      input_files=input_files,
                                                      upload_short_id=upload.short_id,
                                                      experiment_url=experiment_url)
                if experiment.status == database.Status.ERROR:
                    app.logger.info("Experiment is errored")
                    return render_template('setup.html', filename=filename,
                                           built=True, error=True,
                                           log=experiment.get_log(0),
                                           upload_short_id=upload.short_id,
                                           experiment_url=experiment_url)
                # If it's currently building, show the log
                elif experiment.status == database.Status.BUILDING:
                    app.logger.info("Experiment is currently building")
                    return render_template('setup.html', filename=filename,
                                           built=False, log=experiment.get_log(0),
                                           upload_short_id=upload.short_id,
                                           experiment_url=experiment_url)
        # Else, trigger the build
                else:
                    if experiment.status == database.Status.NOBUILD:
                        app.logger.info("Triggering a build, sending message")
                        experiment.status = database.Status.QUEUED
                        tasks.publish_build_task(experiment.hash)
                        return render_template('setup.html', filename=filename,
                                                built=False,
                                                upload_short_id=upload.short_id,
                                                experiment_url=experiment_url)
    finally:
        session.commit()


