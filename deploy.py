#!/usr/bin/env python3


import subprocess
import sys
import tempfile


class Error(Exception):
    def __init__(self, message):
        super().__init__(message)


# A customizable logger.
class Logger(object):
    def _write(self, stream, output):
        if output:
            stream.write(output)
            stream.flush()

    def _write_stdout(self, output):
        self._write(sys.stdout, output)

    def _write_stderr(self, output):
        self._write(sys.stderr, output)

    def log_task(self, task):
        self._write_stdout('# %s\n' % task)

    def __call__(self, task):
        self.log_task(task)

    def log_shell_command(self, command):
        self._write_stdout('$ %s\n' % ' '.join(command))

    def log_shell_stdout(self, output):
        self._write_stdout(output)

    def log_shell_stderr(self, output):
        self._write_stderr(output)


# Provides access to local shell.
class LocalShell(object):
    def __init__(self, log):
        self.log = log

    def run(self, command, may_fail=False):
        if not isinstance(command, list):
            command = command.split()

        self.log.log_shell_command(command)
        process = subprocess.Popen(command, bufsize=1,
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)

        stdout = []
        while process.poll() is None:
            while True:
                chunk = process.stdout.read(1).decode('utf-8')
                if not chunk:
                    break

                self.log.log_shell_stdout(chunk)
                stdout.append(chunk)

            while True:
                chunk = process.stderr.read(1).decode('utf-8')
                if not chunk:
                    break

                self.log.log_shell_stderr(chunk)

        stdout = ''.join(stdout)
        status = process.returncode

        if not may_fail and status != 0:
            raise Error('Shell command returned %d.' % process.returncode)

        return status, stdout


# Provides access to a Docker container.
class DockerContainerShell(object):
    def __init__(self, container_name, shell):
        self.container_name = container_name
        self.shell = shell
        self.log = shell.log

    def run(self, command, may_fail=False):
        if not isinstance(command, list):
            command = command.split()

        command = ['docker', 'exec', '-it', self.container_name,
                   'sh', '-c', '%s' % ' '.join(command)]
        return self.shell.run(command, may_fail)

    def does_file_exist(self, path):
        status, stdout = self.shell.run(
            ['docker', 'exec', '-it', self.container_name,
             'test', '-e', path],
            may_fail=True)

        # self.log('Status: ' + repr(status))
        return status == 0

    def write_file(self, path, content):
        with tempfile.NamedTemporaryFile() as f:
            f.write(content)
            f.flush()

            self.shell.run(
                ['docker', 'cp', f.name,
                 '%s:%s' % (self.container_name, path)])


class Ubuntu(object):
    def __init__(self, shell):
        self.shell = shell

    def _apt_get(self, args):
        self.shell.run(['DEBIAN_FRONTEND=noninteractive', 'apt-get'] + args)

    def update(self):
        # TODO: Do it once per session.
        self._apt_get(['update'])

    def upgrade(self):
        # TODO: Do it once per session.
        self._apt_get(['upgrade', '--yes'])

    def update_upgrade(self):
        self.update()
        self.upgrade()

    def install_packages(self, packages):
        # TODO: Remember installed packages and do not try to install them
        #       again.
        self._apt_get(['install', '--yes'] + packages)


def main():
    shell = DockerContainerShell(container_name='phabricator',
                                 shell=LocalShell(Logger()))
    target = Ubuntu(shell)

    # '''
    target.update_upgrade()

    # https://secure.phabricator.com/source/phabricator/browse/master/scripts/install/install_ubuntu.sh
    target.install_packages(
        ['mariadb-server'])
    target.install_packages(
        ['apache2',
         'libapache2-mod-php'])
    target.install_packages(
        ['git',
         'php',
         'php-mysql',
         'php-gd',
         'php-curl',
         'php-apcu',
         'php-cli',
         'php-json',
         'php-mbstring',
         'python-pygments',
         'mercurial',
         'subversion',
         # 'sendmail',  # TODO: Do we need it?
         'imagemagick'])

    phabricator_components = [
        'libphutil',
        'arcanist',
        'phabricator',
    ]

    for comp in phabricator_components:
        if not target.shell.does_file_exist('/opt/%s' % comp):
            target.shell.run(
                'cd /opt && '
                'git clone https://github.com/phacility/%s.git' % comp)
        else:
            target.shell.run(
                'cd /opt && '
                'cd %s && git pull' % comp)

    target.shell.write_file('/etc/apache2/sites-available/phabricator.conf',
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
    target.shell.run('service mysql restart')
    # '''

    # Drop Phabricator MySQL user $PH_MYSQL_USER before trying to create it.
    # Create Phabricator MySQL user $PH_MYSQL_USER.
    # Grant usage rights on phabricator_* to Phabricator MySQL user $PH_MYSQL_USER.
    # (https://coderwall.com/p/ne1thg/phabricator-mysql-permissions)
    target.shell.run('mysql -u root --execute "%s"' % (
        """DROP USER 'phab'@'localhost'; """),
        may_fail=True)

    target.shell.run('mysql -u root --execute "%s"' % (
        """CREATE USER 'phab'@'localhost' IDENTIFIED BY '5bzc7KahM3AroaG'; """
        """GRANT SELECT, INSERT, UPDATE, DELETE, EXECUTE, SHOW VIEW ON \`phabricator\_%\`.* TO 'phab'@'localhost';"""))
    # target.shell.run('service mysql restart')

    target.shell.run('/opt/phabricator/bin/config set mysql.user phab')
    target.shell.run('/opt/phabricator/bin/config set mysql.pass 5bzc7KahM3AroaG')

    # Configure server timezone.
    target.shell.run(
        r"""sed -i "/date\.timezone =/{ s#.*#date.timezone = 'Europe/London'# }" /etc/php/7.2/apache2/php.ini""")
    target.shell.run('service apache2 restart')

    # Setup MySQL Schema.
    target.shell.run('service apache2 stop')
    target.shell.run('/opt/phabricator/bin/phd stop')

    target.shell.run('/opt/phabricator/bin/storage upgrade --force --user root')

    '''
---
    dbg "Executing Phabricator's storage upgrade"
    p=$(sed -nr '/^password/{s/password = //p}' ~/.my.cnf)
    runas_phab ${PH_ROOT}/phabricator/bin/storage upgrade --force --user root --password ${p}
---
    '''

    target.shell.run('service apache2 start')

    # OPcache should be configured to never revalidate code.
    target.shell.run(
        r"""sed -i "/opcache\.validate_timestamps=/{ s#.*#opcache.validate_timestamps = 0# }" /etc/php/7.2/apache2/php.ini""")
    target.shell.run('service apache2 restart')

    # Enable Pygments.
    target.shell.run('/opt/phabricator/bin/config set pygments.enabled true')

    # Configure 'post_max_size'.
    target.shell.run(
        r"""sed -i "/post_max_size/{ s/.*/post_max_size = 32M/ }" /etc/php/7.2/apache2/php.ini""")
    target.shell.run('service apache2 restart')

    # Configure base URI.
    target.shell.run('/opt/phabricator/bin/config set phabricator.base-uri \'http://172.19.0.5/\'')

    # Configure 'max_allowed_packet'.
    target.shell.run('mysql -u root -p5bzc7KahM3AroaG --execute "%s"' % (
        'SET GLOBAL max_allowed_packet=33554432;'))
    target.shell.run('service mysql restart')

    # Set MySQL STRICT_ALL_TABLES mode.
    # TODO: We do this in the config file.
    # target.shell.run('mysql -u root -p5bzc7KahM3AroaG --execute "%s"' % (
    #     'SET GLOBAL sql_mode=STRICT_ALL_TABLES;'))
    # target.shell.run('service mysql restart')

    # Configure 'innodb_buffer_pool_size'.
    target.shell.write_file('/etc/mysql/mariadb.conf.d/99-phabricator_tweaks.cnf',
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

    target.shell.run('mkdir -p /opt/repos')
    target.shell.run('/opt/phabricator/bin/config set repository.default-local-path /opt/repos')

    target.shell.run('mkdir -p /opt/files')
    target.shell.run('chown -R www-data:www-data /opt/files')
    target.shell.run('/opt/phabricator/bin/config set storage.local-disk.path /opt/files')

    target.shell.run('/opt/phabricator/bin/config set metamta.mail-adapter PhabricatorMailImplementationPHPMailerAdapter')

    target.shell.run('service mysql restart')
    target.shell.run('/opt/phabricator/bin/phd restart')
    target.shell.run('service apache2 restart')
    # '''

    # '''
    target.shell.run('service apache2 start')
    target.shell.run('a2dissite 000-default')
    target.shell.run('a2ensite phabricator')
    target.shell.run('a2enmod rewrite')
    target.shell.run('service apache2 restart')
    target.shell.run('service mysql restart')
    target.shell.run('/opt/phabricator/bin/phd restart')
    # '''

    target.shell.run('ps aux')


if __name__ == '__main__':
    main()
