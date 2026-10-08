"""Importing a world from an uploaded .zip.

The zip comes from the browser, so nothing in it is trusted. Every entry is
checked before anything is written:

- no absolute paths, drive letters, ".." parts or symlinks, so an entry can't
  land outside the world folder (zip slip);
- a cap on the number of entries and on the bytes actually unpacked, counted
  while writing rather than taken from the zip's headers, which can lie
  (zip bombs).

The world itself is the folder holding level.dat. Zips made from a single
player save ("My World/level.dat"), from a server folder ("world/level.dat",
maybe with "world_nether/" and "world_the_end/" next to it) or with level.dat
at the top are all accepted. Only the world folders are imported; anything
else in the zip (server.properties, plugins, jars) is ignored, since the
dashboard writes the server's own files from world.json.
"""

import os
import shutil
import stat
import zipfile

# Folder names the server uses for the overworld, nether and end. itzg's
# LEVEL defaults to "world"; Spigot keeps the other two dimensions of a
# pre-26.1 world in sibling folders.
TARGETS = ("world", "world_nether", "world_the_end")
SUFFIXES = ("", "_nether", "_the_end")

MAX_ENTRIES = 500_000
CHUNK = 1024 * 1024


class UploadError(ValueError):
    """The upload can't be imported; the message says why, for the user."""


def _clean_parts(name):
    """Split a zip entry name into safe path parts, or raise UploadError."""
    if "\x00" in name:
        raise UploadError("The zip has an entry with an invalid name.")
    # Zips made on Windows sometimes use backslashes.
    path = name.replace("\\", "/")
    if path.startswith("/") or (len(path) > 1 and path[1] == ":"):
        raise UploadError(f"The zip has an entry with an absolute path ({name!r}).")
    parts = [p for p in path.split("/") if p not in ("", ".")]
    if ".." in parts:
        raise UploadError(f"The zip has an entry that points outside its folder ({name!r}).")
    return parts


def _is_symlink(info):
    return stat.S_ISLNK(info.external_attr >> 16)


def plan(zf):
    """Work out what to extract. Returns [(prefix_parts, target_folder)].

    Raises UploadError if the zip is unsafe or has no single world in it.
    """
    infos = zf.infolist()
    if len(infos) > MAX_ENTRIES:
        raise UploadError(f"The zip has more than {MAX_ENTRIES} entries.")
    roots = []
    for info in infos:
        parts = _clean_parts(info.filename)
        if _is_symlink(info):
            raise UploadError(f"The zip contains a symlink ({info.filename!r}), which isn't allowed.")
        if parts and parts[0] == "__MACOSX":
            continue
        if parts and parts[-1] == "level.dat" and not info.is_dir():
            roots.append(tuple(parts[:-1]))
    if not roots:
        raise UploadError("No world found in the zip: it needs a folder with a level.dat in it.")

    depth = min(len(r) for r in roots)
    top = sorted(r for r in roots if len(r) == depth)
    if len(top) == 1:
        return [(top[0], "world")]
    # Several worlds side by side: accept X with X_nether and/or X_the_end.
    names = {r[-1]: r for r in top}
    base = min(names, key=len)
    if set(names) <= {base + s for s in SUFFIXES}:
        return [(names[base + s], t) for s, t in zip(SUFFIXES, TARGETS) if base + s in names]
    raise UploadError(
        "The zip holds more than one world (" + ", ".join("/".join(r) for r in top)
        + "). Upload one world at a time."
    )


def extract(zf, mapping, dest, max_bytes):
    """Extract the planned folders into dest/<target>. Returns bytes written.

    dest must be an empty directory. Stops with UploadError once more than
    max_bytes have been unpacked.
    """
    written = 0
    dest_real = os.path.realpath(dest)
    for info in zf.infolist():
        parts = _clean_parts(info.filename)
        for prefix, target in mapping:
            if tuple(parts[:len(prefix)]) == prefix and len(parts) > len(prefix):
                rel = parts[len(prefix):]
                break
        else:
            continue
        path = os.path.join(dest, target, *rel)
        # Belt and braces after _clean_parts: the final path must stay in dest.
        if not os.path.realpath(path).startswith(dest_real + os.sep):
            raise UploadError(f"The zip has an entry that points outside its folder ({info.filename!r}).")
        if info.is_dir():
            os.makedirs(path, exist_ok=True)
            continue
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with zf.open(info) as src, open(path, "wb") as out:
            while True:
                chunk = src.read(CHUNK)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    raise UploadError(
                        f"The zip unpacks to more than {max_bytes // (1024 * 1024)} MB, which is over the limit."
                    )
                out.write(chunk)
    return written


def import_zip(fileobj, name, data_dir, trash_dir, stamp, max_bytes):
    """Replace the world folders in data_dir with the world in the zip.

    Unpacks into a staging folder first, so a bad zip changes nothing. Any
    world folders already in data_dir are moved to trash_dir rather than
    deleted, as <name>-<folder>-<stamp>. Returns (bytes_unpacked, [moved_aside_folder_names]).
    """
    try:
        zf = zipfile.ZipFile(fileobj)
    except (zipfile.BadZipFile, OSError) as e:
        raise UploadError("That file isn't a valid .zip.") from e
    with zf:
        mapping = plan(zf)
        os.makedirs(data_dir, exist_ok=True)
        staging = os.path.join(data_dir, f".upload-{stamp}")
        os.makedirs(staging)
        try:
            try:
                size = extract(zf, mapping, staging, max_bytes)
            except (zipfile.BadZipFile, zipfile.LargeZipFile, EOFError, NotImplementedError) as e:
                raise UploadError(f"The zip couldn't be read ({e}).") from e
            moved = []
            for target in TARGETS:
                current = os.path.join(data_dir, target)
                if os.path.exists(current):
                    os.makedirs(trash_dir, exist_ok=True)
                    aside = f"{name}-{target}-{stamp}"
                    os.rename(current, os.path.join(trash_dir, aside))
                    moved.append(aside)
            for _, target in mapping:
                os.rename(os.path.join(staging, target), os.path.join(data_dir, target))
        finally:
            shutil.rmtree(staging, ignore_errors=True)
    return size, moved
