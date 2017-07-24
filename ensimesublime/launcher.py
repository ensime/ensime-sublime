# coding: utf-8

import errno
import os
import signal
import socket
import subprocess
import datetime
from abc import ABCMeta, abstractmethod
from fnmatch import fnmatch

from util import catch, Util
from errors import LaunchError, InvalidJavaPathError


class EnsimeProcess(object):

    def __init__(self, cache_dir, process, cleanup):
        self.cache_dir = cache_dir
        self.process = process
        self.__stopped_manually = False
        self.__cleanup = cleanup

    def stop(self):
        if self.process is None:
            return
        try:
            os.kill(self.process.pid, signal.SIGTERM)
        except PermissionError:
            subprocess.Popen("taskkill /F /T /PID %i" % self.process.pid , shell=True)
        self.__cleanup()
        self.__stopped_manually = True

    def aborted(self):
        return not (self.__stopped_manually or self.is_running())

    def is_running(self):
        # What? If there's no process, it's running? This is mad confusing.
        return self.process is None or self.process.poll() is None

    def is_ready(self):
        if not self.is_running():
            return False
        try:
            port = self.http_port()
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect(("127.0.0.1", port))
            s.close()
            return True
        except:
            return False

    def http_port(self):
        return int(Util.read_file(os.path.join(self.cache_dir, "http")))


class EnsimeLauncher(object):
    """Launches ENSIME processes"""

    def __init__(self, config):
        self.config = config
        assembly = AssemblyJar(config, config['root-dir'])

        # Do we need to check if "ensime-server-jars" is defined in .ensime
        if assembly.isinstalled():
            self.strategy = assembly
        else:
            self.strategy = DotEnsimeLauncher(config)

    def launch(self):
        return self.strategy.launch()


class LaunchStrategy:
    """A strategy for how to install and launch the ENSIME server.

    Newer build tool versions like sbt-ensime since 1.12.0 may support
    installing the server and publishing the jar locations in ``.ensime``
    so that clients don't need to handle installation. Strategies exist to
    support older versions and build tools that haven't caught up to this.

    Args:
        config (ProjectConfig): Configuration for the server instance's project.
    """
    __metaclass__ = ABCMeta

    def __init__(self, config):
        self.config = config

    @abstractmethod
    def isinstalled(self):
        """Whether ENSIME has been installed satisfactorily for the launcher."""
        raise NotImplementedError

    @abstractmethod
    def launch(self):
        """Launches a server instance for the configured project.

        Returns:
            EnsimeProcess: A process handle for the launched server.

        Raises:
            LaunchError: If server can't be launched according to the strategy.
        """
        raise NotImplementedError

    def _start_process(self, classpath):
        """Given a classpath prepared for running ENSIME, spawns a server process
        in a way that is otherwise agnostic to how the strategy installs ENSIME.

        Args:
            classpath (list of str): list of paths to jars or directories
            (Within this function the list is joined with a system dependent
            path separator to create a single string argument to suitable to 
            pass to ``java -cp`` as a classpath)

        Returns:
            EnsimeProcess: A process handle for the launched server.
        """
        cache_dir = self.config['cache-dir']
        java_flags = self.config['java-flags']

        Util.mkdir_p(cache_dir)
        log_path = os.path.join(cache_dir, "server.log")
        with open(log_path, "w") as f:
            now = datetime.datetime.now()
            tm = now.strftime("%Y-%m-%d %H:%M:%S.%f")
            f.write("{}: {}\n".format(tm, "Initializing ensime process"))
        log = open(log_path, "w")        
        null = open(os.devnull, "r")
        java = os.path.join(self.config['java-home'], 'bin', 'java' if os.name != 'nt' else 'java.exe')

        if not os.path.exists(java):
            raise InvalidJavaPathError(errno.ENOENT, 'No such file or directory', java)
        elif not os.access(java, os.X_OK):
            raise InvalidJavaPathError(errno.EACCES, 'Permission denied', java)

        args = (
            [java, "-cp", (':' if os.name != 'nt' else ';').join(classpath)] +
            [a for a in java_flags if a] +
            ["-Densime.config={}".format(os.path.join(self.config['root-dir'], '.ensime')),
             "org.ensime.server.Server"])
        process = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow |= 1  # SW_SHOWNORMAL
            creationflags = 0x08000000  # CREATE_NO_WINDOW
            process = subprocess.Popen(
                args,
                stdin=null,
                stdout=log,
                stderr=subprocess.STDOUT,
                startupinfo=startupinfo,
                creationflags=creationflags)
        else:
            process = subprocess.Popen(
                args,
                stdin=null,
                stdout=log,
                stderr=subprocess.STDOUT)
        pid_path = os.path.join(cache_dir, "server.pid")
        Util.write_file(pid_path, str(process.pid))
        http_path = os.path.join(cache_dir, "http")
        port_path = os.path.join(cache_dir, "port")

        def on_stop():
            log.close()
            null.close()
            for path in [pid_path, http_path, port_path]:
                with catch(Exception):
                    os.remove(path)

        return EnsimeProcess(cache_dir, process, on_stop)


class AssemblyJar(LaunchStrategy):
    """Launches an ENSIME assembly jar if found in ``~/.config/ensime-vim`` (or
    base_dir). This is intended for ad hoc local development builds, or behind-
    the-firewall corporate installs. See:

    http://ensime.github.io/contributing/#manual-qa-testing
    """

    def __init__(self, config, base_dir):
        super(AssemblyJar, self).__init__(config)
        self.base_dir = os.path.realpath(base_dir)
        self.jar_path = None
        self.toolsjar = os.path.join(config['java-home'], 'lib', 'tools.jar')

    def isinstalled(self):
        if not os.path.exists(self.base_dir):
            return False
        scala_minor = self.config['scala-version'][:4]
        for fname in os.listdir(self.base_dir):
            if fnmatch(fname, "ensime_" + scala_minor + "*-assembly.jar"):
                self.jar_path = os.path.join(self.base_dir, fname)
                return True

        return False

    def launch(self):
        if not self.isinstalled():
            raise LaunchError('ENSIME assembly jar not found in {}'.format(self.base_dir))

        classpath = [self.jar_path, self.toolsjar] + self.config['scala-compiler-jars']
        return self._start_process(classpath)


class DotEnsimeLauncher(LaunchStrategy):
    """Launches a pre-installed ENSIME via jar paths in ``.ensime``."""

    def __init__(self, config):
        super(DotEnsimeLauncher, self).__init__(config)
        server_jars = self.config['ensime-server-jars']
        compiler_jars = self.config['scala-compiler-jars']

        # Order is important so that monkeys takes precedence
        self.classpath = server_jars + compiler_jars

    def isinstalled(self):
        return all([os.path.exists(jar) for jar in self.classpath])

    def launch(self):
        if not self.isinstalled():
            raise LaunchError('Some jars reported by .ensime do not exist: {}'
                              .format(self.classpath))
        return self._start_process(self.classpath)
