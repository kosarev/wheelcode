#!/usr/bin/env python3


import posixpath
import subprocess
import sys
import tempfile


class Error(Exception):
    def __init__(self, message):
        super().__init__(message)


# Makes sure all arguments passed are identical.
def _identical(*args):
    if len(set(args)) > 1:
        raise Error('These objects are required to be identical: %s' % repr(args))
    return args[0]


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
        self.log = shell.log

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

    def _manage_service(self, service, action):
        self.shell.run(['service', service, action])


class MariaDB(object):
    def __init__(self, system):
        self.system = system
        self.shell = system.shell
        self.log = system.log

        self._started = False

    def install(self):
        self.system.update_upgrade()
        self.system.install_packages(['mariadb-server'])

    def _execute(self, commands, may_fail=False):
        # We need the daemon to be started.
        self.start()

        self.shell.run(
            command='mysql -u root --execute "%s"' % commands,
            may_fail=may_fail)

    def add_user(self, user, password, privileges, objects):
        # Drop existing user with the same name, if any.
        # TODO: How can we make sure the failure (if any) is due
        # to non-existing user?
        self._execute("DROP USER '{user}'@'localhost'; ".format(
                          user=user),
                      may_fail=True)

        # Create new user and grant specified privileges.
        self._execute(
            "CREATE USER '{user}'@'localhost' IDENTIFIED BY '{password}'; "
            "GRANT {privileges} ON {objects} TO '{user}'@'localhost';".format(
                user=user,
                password=password,
                privileges=privileges,
                objects=objects))

    def _manage(self, action):
        self.system._manage_service('mysql', action)

    def start(self):
        if not self._started:
            self._manage('start')
            self._started = True

    def restart(self):
        self._manage('restart')
        self._started = True


class Apache2(object):
    def __init__(self, system):
        self.system = system
        self.shell = system.shell
        self.log = system.log

        self._started = False

    def install(self):
        self.system.update_upgrade()
        self.system.install_packages(
            ['apache2',
             'libapache2-mod-php',  # TODO: Not all setups need this.
            ])

    def _manage(self, action):
        self.system._manage_service('apache2', action)

    def start(self):
        if not self._started:
            self._manage('start')
            self._started = True

    def restart(self):
        self._manage('restart')
        self._started = True

    def stop(self):
        if self._started:
            self._manage('stop')
            self._started = False


class Phabricator(object):
    def __init__(self, mysql, webserver):
        self.mysql = mysql
        self.webserver = webserver
        self.system = _identical(self.mysql.system, self.webserver.system)
        self.shell = self.system.shell
        self.log = self.mysql.log

        self.mysql_user = 'phab'
        self.mysql_password = '5bzc7KahM3AroaG'

        self._base_path = '/opt'
        self._phabricator_path = posixpath.join(self._base_path, 'phabricator')
        self._arcanist_path = posixpath.join(self._base_path, 'arcanist')
        self._libphutil_path = posixpath.join(self._base_path, 'libphutil')

        self._components = [
            ('libphutil', self._libphutil_path),
            ('arcanist', self._arcanist_path),
            ('phabricator', self._phabricator_path),
        ]

    def _config_set(self, id, value):
        config_path = posixpath.join(self._phabricator_path, 'bin', 'config')
        self.shell.run([config_path, 'set', id, value])

    def _storage(self, args):
        storage_path = posixpath.join(self._phabricator_path, 'bin', 'storage')
        self.shell.run([storage_path] + args)

    def install(self):
        self.system.update_upgrade()

        self.mysql.install()

        self.log('Create the Phabricator MySQL user.')
        # https://coderwall.com/p/ne1thg/phabricator-mysql-permissions
        self.mysql.add_user(
            user=self.mysql_user, password=self.mysql_password,
            privileges='SELECT, INSERT, UPDATE, DELETE, EXECUTE, SHOW VIEW',
            objects='\`phabricator\_%\`.*')

        self.webserver.install()

        self.shell.write_file('/etc/apache2/sites-available/phabricator.conf',
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

        # https://secure.phabricator.com/source/phabricator/browse/master/scripts/install/install_ubuntu.sh
        # https://gist.github.com/sparrc/b4eff48a3e7af8411fc1
        self.system.install_packages(
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

        self.log("Retrieve phabricator components.")
        for component_name, path in self._components:
            dir = posixpath.dirname(path)
            if not self.shell.does_file_exist(path):
                self.shell.run(
                    'cd %s && '
                    'git clone https://github.com/phacility/%s.git' % (
                        dir, component_name))
            else:
                self.shell.run(
                    'cd %s && '
                    'git pull' % path)

        self.log("Set Phabricator MySQL user credentials.")
        self._config_set('mysql.user', self.mysql_user)
        self._config_set('mysql.pass', self.mysql_password)

        # Configure server timezone.
        self.shell.run(
            r"""sed -i "/date\.timezone =/{ s#.*#date.timezone = 'Etc/UTC'# }" /etc/php/7.2/apache2/php.ini""")
        self.webserver.restart()

        # Setup MySQL Schema.
        self.webserver.stop()
        self.stop()

        # TODO: Have a password for the root MySQL user.
        self._storage(['upgrade', '--force', '--user', 'root'])

        self.webserver.start()

        # OPcache should be configured to never revalidate code.
        self.shell.run(
            r"""sed -i "/opcache\.validate_timestamps=/{ s#.*#opcache.validate_timestamps = 0# }" /etc/php/7.2/apache2/php.ini""")
        self.webserver.restart()

        self.log('Enable Pygments.')
        self._config_set('pygments.enabled', 'true')

        # Configure 'post_max_size'.
        self.shell.run(
            r"""sed -i "/post_max_size/{ s/.*/post_max_size = 32M/ }" /etc/php/7.2/apache2/php.ini""")
        self.webserver.restart()

        self.log('Configure base URI.')
        self._config_set('phabricator.base-uri', "'http://172.19.0.5/'")

        # Configure 'innodb_buffer_pool_size'.
        self.shell.write_file('/etc/mysql/mariadb.conf.d/99-phabricator_tweaks.cnf',
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

        self.shell.run('mkdir -p /opt/repos')
        self._config_set('repository.default-local-path', '/opt/repos')

        self.shell.run('mkdir -p /opt/files')
        self.shell.run('chown -R www-data:www-data /opt/files')
        self._config_set('storage.local-disk.path', '/opt/files')

        self._config_set('metamta.mail-adapter',
                         'PhabricatorMailImplementationPHPMailerAdapter')

        self.mysql.restart()
        self.restart()
        self.webserver.restart()
        # '''

        # '''
        self.webserver.start()
        self.shell.run('a2dissite 000-default')
        self.shell.run('a2ensite phabricator')
        self.shell.run('a2enmod rewrite')
        self.webserver.restart()
        self.mysql.restart()
        self.restart()
        # '''

        self.shell.run('ps aux')

    def _manage(self, action):
        phd_path = posixpath.join(self._phabricator_path, 'bin', 'phd')
        self.shell.run([phd_path, action])

    def restart(self):
        self._manage('restart')

    def stop(self):
        self._manage('stop')


def main():
    local_shell = LocalShell(Logger())
    docker_shell = DockerContainerShell(container_name='phabricator',
                                        shell=local_shell)
    system = Ubuntu(docker_shell)
    mysql = MariaDB(system)
    webserver = Apache2(system)
    phab = Phabricator(mysql=mysql,
                       webserver=webserver)

    phab.install()


if __name__ == '__main__':
    main()
