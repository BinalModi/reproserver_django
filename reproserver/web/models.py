from django.db import models
from django.utils import timezone
from common.shortid import MultiShortIDs
import enum
import logging
import os

class Status(enum.Enum):
    ("1", "NOBUILD"),
    ("2","QUEUED"),
    ("3","BUILDING"),
    ("4","BUILT"),
    ("0","ERROR")


class Experiment(models.Model):
    """Experiments available on the server.

    Those match experiment files that were uploaded, whether or not an image
    has been built.

    Note that no filename is here, since the file might have been uploaded
    multiple times with different names.
    """

    hash = models.TextField(primary_key=True)
    status = models.TextField(choices = Status, default="1")
    docker_image = models.TextField(null=True)
    last_access = models.DateTimeField(default=timezone.now())

    uploads = models.ManyToManyField('Upload',related_name='+')
    runs = models.ManyToManyField('Run', related_name='+')
    parameters = models.ManyToManyField('Parameter', related_name='+')
    paths = models.ManyToManyField('Path', related_name='+')
    log = models.ManyToManyField('BuildLogLine', related_name='+')

    def get_log(self, from_line=0):
        return [log.line for log in self.log[from_line:]]

    def __repr__(self):
        return "<Experiment hash=%r, status=%r, docker_image=%r>" % (
            self.hash,
            self.status,
            self.docker_image)

    class Meta:
        db_table = "experiments"

class Upload(models.Model):
    """An upload of an experiment.

    There can be multiple uploads for the same experiment, each of them
    associated with a different uploader and filename.

    This is not used by the application, but might be important for accounting
    purposes.
    """
    
    filename = models.TextField()
    experiment_hash = models.ForeignKey(Experiment,unique='True', on_delete=models.CASCADE,related_name="+")
    
    # experiment = models.OneToOneField('Experiment', on_delete= models.CASCADE)
    #back_populates='uploads')
    submitted_ip = models.TextField(null=True)
    provider_key = models.TextField(null=True, db_index=True)
    # Since we want a time for everytime its created and dont want to replace the time if modified
    timestamp = models.DateTimeField(default=timezone.now())

    @property
    def short_id(self):
        short_ids = MultiShortIDs(os.environ['SHORTIDS_SALT'])
        return short_ids.encode('uploads', self.id)

    def __repr__(self):
        return ("<Upload id=%d, experiment_hash=%r, filename=%r, "
                "submitted_ip=%r, timestamp=%r>") % (
            self.id, self.experiment_hash, self.filename,
            self.submitted_ip, self.timestamp)

    class Meta:
        db_table = "uploads"

class Parameter(models.Model):
    """An experiment parameter.

    Once the experiment has been built, the builder adds the list of its
    parameters to the database, that it extracted from the package metadata.
    Those are displayed to the user when running the experiment.
    """

    experiment_hash = models.ForeignKey(Experiment, on_delete=models.CASCADE,related_name="+")
    # experiment = models.OneToOneField('Experiment', models.CASCADE)
    
    name = models.TextField(null=False)
    description = models.TextField()
    optional = models.BooleanField()
    default = models.TextField(null=True)

    def __repr__(self):
        return ("<Parameter id=%d, experiment_hash=%r, name=%r, optional=%r, "
                "default=%r") % (
            self.id, self.experiment_hash, self.name, self.optional,
            self.default)
    
    class Meta:
        db_table = "parameters"


class Path(models.Model):
    """Path to an input/output file in the experiment.
    """

    experiment_hash = models.ForeignKey(Experiment, on_delete=models.CASCADE,related_name="+")
    # experiment = models.OneToOneField('Experiment', models.CASCADE)
                              
    is_input = models.BooleanField()
    is_output = models.BooleanField()
    name = models.TextField()
    path = models.TextField()

    def __repr__(self):
        if self.is_input and self.is_output:
            descr = "input+output"
        elif self.is_input:
            descr = "input"
        elif self.is_output:
            descr = "output"
        else:
            descr = "(NO FLAG)"
        return "<Path id=%d, experiment_hash=%r, %s, name=%r>" % (
            self.id, self.experiment_hash, descr, self.name)

    class Meta:
        db_table = "paths"


class Run(models.Model):
    """A run.

    This is created when a user submits parameters and triggers the run of an
    experiment. It contains logs and the location of output files.
    """

    experiment_hash = models.ForeignKey(Experiment, on_delete=models.CASCADE,related_name="+")
    # experiment = models.OneToOneField('Experiment',models.CASCADE)
    
    upload_id = models.ForeignKey(Upload,on_delete=models.PROTECT,related_name="+")
    upload_Run = models.OneToOneField('Upload',models.CASCADE)
    
    submitted = models.DateTimeField(default=timezone.now())
    started = models.DateField(null=True)
    done = models.DateField(null=True)

    parameter_values = models.ManyToManyField('ParameterValue',related_name="+")
    input_files = models.ManyToManyField('InputFile',related_name="+")

    log = models.ManyToManyField('RunLogLine',related_name="+")
    output_files = models.ManyToManyField('OutputFile',related_name="+")

    @property
    def short_id(self):
        return short_ids.encode('run', self.id)

    def get_log(self, from_line=0):
        return [log.line for log in self.log[from_line:]]

    def __repr__(self):
        if self.done:
            status = "done"
        elif self.started:
            status = "started"
        else:
            status = "submitted"
        return ("<Run id=%d, experiment_hash=%r, %s, %d parameters, "
                "%d inputs, %d outputs>") % (
            self.id, self.experiment_hash, status, len(self.parameter_values),
            len(self.input_files), len(self.output_files))

    class Meta:
        db_table = "runs"

class BuildLogLine(models.Model):
    """A line of build log.

    FIXME: Storing this in the database is not a great idea.
    """

    experiment_hash = models.ForeignKey(Experiment, on_delete=models.CASCADE,related_name="+")
    # experiment = models.OneToOneField('Experiment',models.CASCADE)
    timestamp = models.DateTimeField(default=timezone.now())
    
    line = models.TextField()

    def __repr__(self):
        return "<BuildLogLine id=%d, experiment_hash=%r>" % (
            self.id, self.experiment_hash)
    
    class Meta:
        db_table = "build_logs"

class RunLogLine(models.Model):
    """A line of run log.

    FIXME: Storing this in the database is not a great idea.
    """
    
    run_id = models.ForeignKey(Run, on_delete=models.CASCADE, related_name="+")
    run_RunLogLineß = models.OneToOneField('Run',models.CASCADE)
    timestamp = models.DateTimeField(default=timezone.now())
    line = models.TextField()

    def __repr__(self):
        return "<RunLogLine id=%d, run_id=%d>" % (self.id, self.run_id)

    class Meta:
        db_table = "run_logs"


class ParameterValue(models.Model):
    """A value for a parameter in a run.
    """
    run_id = models.ForeignKey(Run, on_delete= models.CASCADE,related_name="+")
    run_parameterValue = models.OneToOneField('Run',models.CASCADE)
    name = models.TextField()
    value = models.TextField()

    def __repr__(self):
        return "<ParameterValue id=%d, run_id=%d, name=%r>" % (
            self.id, self.run_id, self.name)

    class Meta:
        db_table = "run_parameters"


class InputFile(models.Model):
    """An input file for a run.
    """

    hash = models.TextField()
    run_id = models.ForeignKey(Run, on_delete=models.CASCADE,related_name="+")
    run_inputFile = models.OneToOneField('Run',on_delete=models.CASCADE)
    name = models.TextField()
    size = models.IntegerField()

    def __repr__(self):
        return "<InputFile id=%d, run_id=%d, hash=%r, name=%r>" % (
            self.id, self.run_id, self.hash, self.name)

    class Meta:
        db_table = "input_files"


class OutputFile(models.Model):
    """An output file from a run.
    """

    hash = models.TextField()
    run_id = models.ForeignKey(Run, on_delete=models.CASCADE,related_name="+")
    run_outputFile = models.OneToOneField('Run',on_delete=models.CASCADE)
    name = models.TextField()
    size = models.IntegerField()

    def __repr__(self):
        return "<OutputFile id=%d, run_id=%d, hash=%r, name=%r>" % (
            self.id, self.run_id, self.hash, self.name)

    class Meta:
        db_table = "output_files"


def purge(url=None):
    _, Session = connect(url)

    session = Session()
    session.query(Experiment).delete()
    session.commit()


def connect(url=None):
    """Connect to the database using an environment variable.
    """
    global short_ids
    short_ids = MultiShortIDs(os.environ['SHORTIDS_SALT'])

    logging.info("Connecting to SQL database")
    if url is None:
        url = 'postgresql://{user}:{password}@{host}/{database}'.format(
            user=os.environ['POSTGRES_USER'],
            password=os.environ['POSTGRES_PASSWORD'],
            host=os.environ['POSTGRES_HOST'],
            database=os.environ['POSTGRES_DB'],
        )
    engine = create_engine(url, echo=False)

    return engine, sessionmaker(bind=engine)
