"""Stand-in for google.colab on the GitHub server.

The notebooks were written for Colab. Here Drive is already synced into
/content/drive/MyDrive, secrets come from environment variables, and there is
nobody to click "upload" or "download".
"""
import os
import sys
import types


class SecretNotFoundError(Exception):
    pass


def _get_secret(name):
    value = os.environ.get(name, "")
    if not value:
        raise SecretNotFoundError(name)
    return value


def _mount(path, *args, **kwargs):
    if not os.path.isdir(os.path.join(path, "MyDrive")):
        raise RuntimeError(f"Google Drive is not synced to {path}/MyDrive")


def _upload(*args, **kwargs):
    raise RuntimeError("No file uploads on the server: the file must be on Google Drive.")


def _download(path, *args, **kwargs):
    pass                                    # results already go to Drive


def _eval_js(*args, **kwargs):
    return None


def install():
    """Register fake google.colab modules so `from google.colab import ...` works."""
    colab = types.ModuleType("google.colab")
    drive = types.ModuleType("google.colab.drive")
    drive.mount = _mount
    files = types.ModuleType("google.colab.files")
    files.upload = _upload
    files.download = _download
    userdata = types.ModuleType("google.colab.userdata")
    userdata.get = _get_secret
    userdata.SecretNotFoundError = SecretNotFoundError
    output = types.ModuleType("google.colab.output")
    output.eval_js = _eval_js
    for name, mod in (("drive", drive), ("files", files), ("userdata", userdata), ("output", output)):
        setattr(colab, name, mod)
        sys.modules["google.colab." + name] = mod
    sys.modules["google.colab"] = colab
    try:
        import google                        # namespace package from google-* libraries
        google.colab = colab
    except ImportError:
        google = types.ModuleType("google")
        google.__path__ = []
        google.colab = colab
        sys.modules["google"] = google
