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
        if not isinstance(command, list):
            command = command.split()

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
        if not isinstance(command, list):
            command = command.split()

        command = ['docker', 'exec', '-it', self.container_name,
                   'sh', '-c', '%s' % ' '.join(command)]
        return self.local_shell.run(command)


# Implements basic target operations.
class Target(object):
    def __init__(self, iface):
        self._iface = iface
        self._completed_actions = set()

    # Executes a shell command.
    def run(self, command, action_id=None):
        # Do not perform actions that have already been marked as
        # completed.
        if action_id and action_id in self._completed_actions:
            return

        self._iface.run(command)

        if action_id:
            self._completed_actions.add(action_id)


def apt_update(target):
    target.run(['apt', 'update'], 'apt_update')


def apt_upgrade(target):
    target.run(['apt', 'upgrade', '-y'], 'apt_upgrade')


def apt_update_upgrade(target):
    apt_update(target)
    apt_upgrade(target)


def main():
    log = Logger()
    iface = DockerContainerInterface('phabricator', log)
    target = Target(iface)

    # apt_update_upgrade(target)
    # target.run(['su', '-'])
    # target.run(['cd', '/root', '&&', 'pwd'])
    # target.run(['cat', '/etc/issue'])
    target.run('sudo ls')


if __name__ == '__main__':
    main()
