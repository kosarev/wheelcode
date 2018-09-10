#!/usr/bin/env python3


import subprocess
import sys
import tempfile


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

    def run_shell_command(self, command, may_fail=False):
        if not isinstance(command, list):
            command = command.split()

        command = ['docker', 'exec', '-it', self.container_name,
                   'sh', '-c', '%s' % ' '.join(command)]
        return self.local_shell.run_shell_command(command, may_fail)

    def does_file_exist(self, path):
        status, stdout = self.local_shell.run_shell_command(
            ['docker', 'exec', '-it', self.container_name,
             'test', '-e', path],
            may_fail=True)

        # self.log('Status: ' + repr(status))
        return status == 0

    def write_file(self, path, content):
        with tempfile.NamedTemporaryFile() as f:
            f.write(content)
            f.flush()

            self.local_shell.run_shell_command(
                ['docker', 'cp', f.name,
                 '%s:%s' % (self.container_name, path)])


# Implements basic target operations.
class Target(object):
    def __init__(self, iface):
        self._iface = iface
        self._completed_actions = set()

    def run_shell_command(self, command, action_id=None, may_fail=False):
        # Do not perform actions that have already been marked as
        # completed.
        if action_id and action_id in self._completed_actions:
            return

        self._iface.run_shell_command(command, may_fail)

        if action_id:
            self._completed_actions.add(action_id)

    def does_file_exist(self, path):
        return self._iface.does_file_exist(path)

    def write_file(self, path, content):
        return self._iface.write_file(path, content)


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
         'php-mbstring',
         'python-pygments'],
        target)

    phabricator_components = [
        'libphutil',
        'arcanist',
        'phabricator',
    ]

    for comp in phabricator_components:
        if not target.does_file_exist('/opt/%s' % comp):
            target.run_shell_command(
                'cd /opt && '
                'git clone https://github.com/phacility/%s.git' % comp)
        else:
            target.run_shell_command(
                'cd /opt && '
                'cd %s && git pull' % comp)

    target.write_file('/etc/apache2/sites-available/phabricator.conf',
                      b"""
<VirtualHost *>
  # Change this to the domain which points to your host.
  ServerName 172.19.0.5

  # Change this to the path where you put 'phabricator' when you checked it
  # out from GitHub when following the Installation Guide.
  #
  # Make sure you include "/webroot" at the end!
  DocumentRoot /opt/phabricator/webroot

  RewriteEngine on
  RewriteRule ^(.*)$          /index.php?__path__=$1  [B,L,QSA]
</VirtualHost>

<Directory "/opt/phabricator/webroot">
    Require all granted
</Directory>
""")
    target.run_shell_command('service mysql restart')

    # Drop Phabricator MySQL user $PH_MYSQL_USER before trying to create it.
    # Create Phabricator MySQL user $PH_MYSQL_USER.
    # Grant usage rights on phabricator_* to Phabricator MySQL user $PH_MYSQL_USER.
    # (https://coderwall.com/p/ne1thg/phabricator-mysql-permissions)
    target.run_shell_command('mysql -u root --execute "%s"' % (
        """DROP USER 'phab'@'localhost'; """),
        may_fail=True)

    target.run_shell_command('mysql -u root --execute "%s"' % (
        """CREATE USER 'phab'@'localhost' IDENTIFIED BY '5bzc7KahM3AroaG'; """
        """GRANT SELECT, INSERT, UPDATE, DELETE, EXECUTE, SHOW VIEW ON \`phabricator\_%\`.* TO 'phab'@'localhost';"""))

    target.run_shell_command('/opt/phabricator/bin/config set mysql.user phab')
    target.run_shell_command('/opt/phabricator/bin/config set mysql.pass 5bzc7KahM3AroaG')
    target.run_shell_command('service mysql restart')
    target.run_shell_command('/opt/phabricator/bin/phd restart')

    # Configure server timezone.
    target.run_shell_command(
        r"""sed -i "/date\.timezone =/{ s#.*#date.timezone = 'Europe/London'# }" /etc/php/7.2/apache2/php.ini""")
    target.run_shell_command('service apache2 restart')

    # Setup MySQL Schema.
    target.run_shell_command('service apache2 stop')
    target.run_shell_command('/opt/phabricator/bin/phd stop')
    target.run_shell_command('/opt/phabricator/bin/storage upgrade --force')
    target.run_shell_command('service apache2 start')

    # OPcache should be configured to never revalidate code.
    target.run_shell_command(
        r"""sed -i "/opcache\.validate_timestamps=/{ s#.*#opcache.validate_timestamps = 0# }" /etc/php/7.2/apache2/php.ini""")
    target.run_shell_command('service apache2 restart')

    # Enable Pygments.
    target.run_shell_command('/opt/phabricator/bin/config set pygments.enabled true')

    # Configure 'post_max_size'.
    target.run_shell_command(
        r"""sed -i "/post_max_size/{ s/.*/post_max_size = 32M/ }" /etc/php/7.2/apache2/php.ini""")
    target.run_shell_command('service apache2 restart')

    # Configure base URI.
    target.run_shell_command('/opt/phabricator/bin/config set phabricator.base-uri \'http://172.19.0.5/\'')

    # Configure 'max_allowed_packet'.
    target.run_shell_command('mysql -u root -p5bzc7KahM3AroaG --execute "%s"' % (
        'SET GLOBAL max_allowed_packet=33554432;'))
    target.run_shell_command('service mysql restart')

    # Set MySQL STRICT_ALL_TABLES mode.
    # TODO: We do this in the config file.
    # target.run_shell_command('mysql -u root -p5bzc7KahM3AroaG --execute "%s"' % (
    #     'SET GLOBAL sql_mode=STRICT_ALL_TABLES;'))
    # target.run_shell_command('service mysql restart')

    # Configure 'innodb_buffer_pool_size'.
    target.write_file('/etc/mysql/mariadb.conf.d/99-phabricator_tweaks.cnf',
                      b"""
# Phabricator recommendations for MySQL.

[mysqld]

sql_mode = STRICT_ALL_TABLES

# Size of the memory area where InnoDB caches table and index data. Actually
# needs 10% more than specified for related cache structures. Phabricator
# whines if this is set to less than 256M. MySQL won't start if it cannot
# allocate the specified amount of memory with this error:
#     InnoDB: Fatal error: cannot allocate memory for the buffer pool
# This happened with 400M pool size (with apache and phd daemons running).
innodb_buffer_pool_size = 1600M

max_allowed_packet = 33554432
""")
    '''

    target.run_shell_command('mkdir -p /opt/repos')
    target.run_shell_command('/opt/phabricator/bin/config set repository.default-local-path /opt/repos')

    target.run_shell_command('/opt/phabricator/bin/config set metamta.mail-adapter PhabricatorMailImplementationPHPMailerAdapter')

    target.run_shell_command('service mysql restart')
    target.run_shell_command('/opt/phabricator/bin/phd restart')
    target.run_shell_command('service apache2 restart')

    '''
    target.run_shell_command('service apache2 start')
    target.run_shell_command('a2dissite 000-default')
    target.run_shell_command('a2ensite phabricator')
    target.run_shell_command('a2enmod rewrite')
    target.run_shell_command('service apache2 restart')
    target.run_shell_command('service mysql start')
    target.run_shell_command('/opt/phabricator/bin/phd start')
    '''

    target.run_shell_command('ps aux')


if __name__ == '__main__':
    main()
