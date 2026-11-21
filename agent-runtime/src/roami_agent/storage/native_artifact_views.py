"""Private, turn-scoped names for native tools that identify files by extension."""

import os
import re
import shutil
import stat
import tempfile
from pathlib import Path

from roami_agent.protocol.errors import DomainError

IMAGE_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


class NativeArtifactViews:
    def __init__(self, data_root):
        self.root = data_root / "agents" / "native-artifact-views"
        self.views = {}

    @staticmethod
    def private_directory(path, *, create=False):
        if create:
            path.mkdir(mode=0o700, exist_ok=True)
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise DomainError("NATIVE_ARTIFACT_VIEW_UNAVAILABLE", 409)

    def recover(self):
        if not self.root.exists() and not self.root.is_symlink():
            return
        self.private_directory(self.root.parent)
        self.private_directory(self.root)
        # Runtime startup holds the existing exclusive agent database lock.
        for path in self.root.iterdir():
            if re.fullmatch("turn-[a-z0-9_]{8}", path.name) and not path.is_symlink():
                self.private_directory(path)
                shutil.rmtree(path)

    def issue(self, turn_id, lease_epoch, reference, blob):
        extension = IMAGE_EXTENSIONS.get(reference["mimeType"])
        digest = reference["sha256"]
        if not extension or not re.fullmatch("[a-f0-9]{64}", digest):
            raise DomainError("NATIVE_ARTIFACT_VIEW_UNAVAILABLE", 409)
        self.private_directory(self.root.parent, create=True)
        self.private_directory(self.root, create=True)
        scope = (turn_id, lease_epoch)
        directory = self.views.get(scope)
        if directory is None:
            directory = tempfile.TemporaryDirectory(prefix="turn-", dir=self.root)
            self.views[scope] = directory
        alias = Path(directory.name) / (digest + extension)
        try:
            alias.symlink_to(blob)
        except FileExistsError:
            if not alias.is_symlink() or alias.readlink() != blob:
                raise DomainError("NATIVE_ARTIFACT_VIEW_UNAVAILABLE", 409) from None
        return str(alias)

    def release(self, turn_id, lease_epoch):
        directory = self.views.pop((turn_id, lease_epoch), None)
        if directory is not None:
            directory.cleanup()

    def close(self):
        for turn_id, lease_epoch in list(self.views):
            self.release(turn_id, lease_epoch)
