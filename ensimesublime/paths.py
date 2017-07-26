import os


def encode_path(path):
    if not path:
        return path

    if os.name == "nt":
        if os.path.isabs(path):
            drive, rest = os.path.splitdrive(path)
            return "/" + drive[:-1].upper() + rest.replace("\\", "/")
        else:
            return path.replace("\\", "/")
    else:
        return path


def decode_path(path):
    if not path:
        return path

    if os.name == "nt":
        if path.startswith("/"):
            path = path[1:]
            iof = path.find("/")
            if iof == -1:
                drive = path
                rest = ""
            else:
                drive = path[:iof]
                rest = path[iof:]
            return (drive + ":" + rest).replace("/", "\\")
        else:
            return path.replace("/", "\\")
    else:
        return path


def same_paths(path1, path2):
    if not path1 or not path2:
        return False
    path1_normalized = os.path.normcase(os.path.realpath(path1))
    path2_normalized = os.path.normcase(os.path.realpath(path2))
    return path1_normalized == path2_normalized


def normalize_path(path):
    if not path:
        return None
    return os.path.normcase(os.path.realpath(path))


def is_subpath(root, wannabe):
    if not root or not wannabe:
        return False
    root = os.path.normcase(os.path.realpath(root))
    wannabe = os.path.normcase(os.path.realpath(wannabe))  # .encode("utf-8")
    return wannabe.startswith(root)


def relative_path(root, wannabe):
    if not root or not wannabe:
        return None
    if not is_subpath(root, wannabe):
        return None
    root = os.path.normcase(os.path.realpath(root))
    wannabe = os.path.normcase(os.path.realpath(wannabe))
    return wannabe[len(root) + 1:]


def root_as_str_from_abspath(path):
    if os.name != "nt":
        return "/"

    # Windows paths are interesting, code below is adjusted from https://pypi.python.org/pypi/pathlib2 z
    sep = '\\'
    altsep = '/'
    ext_namespace_prefix = '\\\\?\\'

    try:
        intern = intern
    except NameError:
        import sys
        intern = sys.intern

    def parse_parts(parts):
        parsed = []

        drv = root = ''
        it = reversed(parts)
        for part in it:
            if not part:
                continue
            if altsep:
                part = part.replace(altsep, sep)
            drv, root, rel = splitroot(part)
            if sep in rel:
                for x in reversed(rel.split(sep)):
                    if x and x != '.':
                        parsed.append(intern(x))
            else:
                if rel and rel != '.':
                    parsed.append(intern(rel))
            if drv or root:
                if not drv:
                    # If no drive is present, try to find one in the previous
                    # parts. This makes the result of parsing e.g.
                    # ("C:", "/", "a") reasonably intuitive.
                    for part in it:
                        if not part:
                            continue
                        if altsep:
                            part = part.replace(altsep, sep)
                        drv = splitroot(part)[0]
                        if drv:
                            break
                break
        if drv or root:
            parsed.append(drv + root)
        parsed.reverse()
        return drv, root, parsed

    def split_extended_path(s, ext_prefix=ext_namespace_prefix):
        prefix = ''
        if s.startswith(ext_prefix):
            prefix = s[:4]
            s = s[4:]
            if s.startswith('UNC\\'):
                prefix += s[:3]
                s = '\\' + s[3:]
        return prefix, s

    def splitroot(part, sep=sep):
        drive_letters = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ')
        first = part[0:1]
        second = part[1:2]
        if (second == sep and first == sep):
            # XXX extended paths should also disable the collapsing of "."
            # components (according to MSDN docs).
            prefix, part = split_extended_path(part)
            first = part[0:1]
            second = part[1:2]
        else:
            prefix = ''
        third = part[2:3]
        if (second == sep and first == sep and third != sep):
            # is a UNC path:
            # vvvvvvvvvvvvvvvvvvvvv root
            # \\machine\mountpoint\directory\etc\...
            #            directory ^^^^^^^^^^^^^^
            index = part.find(sep, 2)
            if index != -1:
                index2 = part.find(sep, index + 1)
                # a UNC path can't have two slashes in a row
                # (after the initial two)
                if index2 != index + 1:
                    if index2 == -1:
                        index2 = len(part)
                    if prefix:
                        return prefix + part[1:index2], sep, part[index2 + 1:]
                    else:
                        return part[:index2], sep, part[index2 + 1:]
        drv = root = ''
        if second == ':' and first in drive_letters:
            drv = part[:2]
            part = part[2:]
            first = third
        if first == sep:
            root = first
            part = part.lstrip(sep)
        return prefix + drv, root, part

    drv, root, parts = parse_parts((path,))
    return normalize_path(os.path.join(drv))
