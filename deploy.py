#!/usr/bin/env python3


import subprocess


# A configurable logger.
class Logger(object):
    def __call__(self, message):
        if message:
            print(message)

    def log_stdin(self, input):
        self('$ ' + input)

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
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)

        stdout, stderr = process.communicate()

        stdout = stdout.decode('utf-8')
        stderr = stderr.decode('utf-8')

        self.log.log_stdout(stdout)
        self.log.log_stderr(stderr)

        assert process.returncode == 0, (
            'Shell command returned %d.' % process.returncode)

        return stdout


# Provides access to a Docker container.
class DockerContainerInterface(object):
    def __init__(self, container_name, log):
        self.container_name = container_name
        self.log = log
        self.local_shell = LocalShell(log)

    def run(self, command):
        command = ['docker', 'exec', '-it', self.container_name] + command
        return self.local_shell.run(command)


def main():
    log = Logger()
    target = DockerContainerInterface('phabricator', log)
    target.run(['ls'])


if __name__ == '__main__':
    main()
