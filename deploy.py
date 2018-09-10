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

    def run_shell_command(self, command, may_fail=False):
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

        stdout = ''.join(stdout)
        status = process.returncode

        if not may_fail:
            assert status == 0, (
                'Shell command returned %d.' % process.returncode)

        return status, stdout


# Provides access to a Docker container.
class DockerContainerInterface(object):
    def __init__(self, container_name, log):
        self.container_name = container_name
        self.log = log
        self.local_shell = LocalShell(log)

    def run_shell_command(self, command):
        if not isinstance(command, list):
            command = command.split()

        command = ['docker', 'exec', '-it', self.container_name,
                   'sh', '-c', '%s' % ' '.join(command)]
        return self.local_shell.run_shell_command(command)

    def does_file_exist(self, path):
        status, stdout = self.local_shell.run_shell_command(
            ['docker', 'exec', '-it', self.container_name,
             'test', '-e', path],
            may_fail=True)

        # self.log('Status: ' + repr(status))
        return status == 0


# Implements basic target operations.
class Target(object):
    def __init__(self, iface):
        self._iface = iface
        self._completed_actions = set()

    def run_shell_command(self, command, action_id=None):
        # Do not perform actions that have already been marked as
        # completed.
        if action_id and action_id in self._completed_actions:
            return

        self._iface.run_shell_command(command)

        if action_id:
            self._completed_actions.add(action_id)

    def does_file_exist(self, path):
        return self._iface.does_file_exist(path)


def aptget_update(target):
    target.run_shell_command(
        ['DEBIAN_FRONTEND=noninteractive',
         'apt-get', 'update'],
        'apt_update')


def aptget_upgrade(target):
    target.run_shell_command(
        ['DEBIAN_FRONTEND=noninteractive',
         'apt-get', 'upgrade', '--yes'],
        'apt_upgrade')


def aptget_update_upgrade(target):
    aptget_update(target)
    aptget_upgrade(target)


def aptget_install(packages, target):
    target.run_shell_command(
        ['DEBIAN_FRONTEND=noninteractive',
         'apt-get', 'install', '--yes'] + packages)


def main():
    log = Logger()
    iface = DockerContainerInterface('phabricator', log)
    target = Target(iface)

    '''
    aptget_update_upgrade(target)

    # https://secure.phabricator.com/source/phabricator/browse/master/scripts/install/install_ubuntu.sh
    aptget_install(
        ['mariadb-server'],
        target)
    aptget_install(
        ['apache2',
         'libapache2-mod-php'],
        target)
    aptget_install(
        ['git',
         'php',
         'php-mysql',
         'php-gd',
         'php-curl',
         'php-apcu',
         'php-cli',
         'php-json',
         'php-mbstring'],
        target)
    '''

    phabricator_components = [
        'libphutil',
        'arcanist',
        'phabricator',
    ]

    for comp in phabricator_components:
        if not target.does_file_exist('/root/%s' % comp):
            target.run_shell_command(
                'cd /root && '
                'git clone https://github.com/phacility/%s.git' % comp)
        else:
            target.run_shell_command(
                'cd /root && '
                'cd %s && git pull' % comp)


    # target.run_shell_command('a2enmod rewrite')

    # target.run_shell_command('service apache2 start')
    # target.run_shell_command('service mysql start')

    # target.run_shell_command('ps aux')

    # target.run_shell_command('mysql --execute "list;"')


if __name__ == '__main__':
    main()
