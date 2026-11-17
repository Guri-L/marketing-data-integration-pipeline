"""Exception hierarchy. Every failure the pipeline raises on purpose is a PipelineError."""


class PipelineError(Exception):
    """Base class for all pipeline errors."""


class ConfigurationError(PipelineError):
    """A required setting or credential is missing or invalid."""


class ExtractionError(PipelineError):
    """A source could not be read. Not retried."""


class TransientExtractionError(ExtractionError):
    """A source failed in a way worth retrying (rate limit, timeout, 5xx)."""


class ValidationError(PipelineError):
    """Extracted records do not match the source's raw contract."""


class LoadError(PipelineError):
    """Records could not be written to the warehouse."""


class TransformError(PipelineError):
    """A SQL model failed to build."""


class DataQualityError(PipelineError):
    """One or more error-severity data quality checks failed."""
