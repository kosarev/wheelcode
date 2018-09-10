#!/usr/bin/env python3


import subprocess
import sys


# A customizable logger.
class Logger(object):
    def __call__(self, message):
        if message:
            sys.stdout.write(message)
            sys.stdout.flush()

    def log_stdin(self, input):
        self('$ %s\n' % input)

    def log_stdout(self, output):
        self(output)

    def log_stderr(self, output):
        self(output)


# Provides access to local shell.
class LocalShell(object):
    def __init__(self, log):
        self.log = log

    def run(self, command):
        self.log.log_stdin(' '.join(command))
        process = subprocess.Popen(command,
                                   bufsize=1,
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)

        stdout = []
        while process.poll() is None:
            while True:
                chunk = process.stdout.read(1).decode('utf-8')
                if not chunk:
                    break

                self.log.log_stdout(chunk)
                stdout.append(chunk)

            while True:
                chunk = process.stderr.read(1).decode('utf-8')
                if not chunk:
                    break

                self.log.log_stderr(chunk)

        assert process.returncode == 0, (
            'Shell command returned %d.' % process.returncode)

        return ''.join(stdout)


# Provides access to a Docker container.
class DockerContainerInterface(object):
    def __init__(self, container_name, log):
        self.container_name = container_name
        self.log = log
        self.local_shell = LocalShell(log)

    def run(self, command):
        command = ['docker', 'exec', '-it', self.container_name] + command
        return self.local_shell.run(command)


# Implements basic target operations.
class Target(object):
    def __init__(self, iface):
        self.iface = iface

    # Executes a shell command.
    def run(self, command):
        return self.iface.run(command)

    def apt_update(self):
        return self.run(['apt', 'update'])

    def apt_upgrade(self):
        return self.run(['apt', 'upgrade', '-y'])


def main():
    log = Logger()
    iface = DockerContainerInterface('phabricator', log)

    target = Target(iface)
    target.apt_update()
    target.apt_upgrade()


if __name__ == '__main__':
    main()
