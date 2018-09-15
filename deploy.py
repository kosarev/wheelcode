#!/usr/bin/env python3


import os
import posixpath
import subprocess
import secrets
import string
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


def generate_password():
    alphabet = string.ascii_letters + string.digits + '._'
    return ''.join(secrets.choice(alphabet) for i in range(16))


# Stores configuration values.
class Config(object):
    def __init__(self, options=dict()):
        self._options = dict()
        for id, value in options.items():
            self[id] = value

    def __contains__(self, id):
        return id in self._options

    def __getitem__(self, id):
        if id in self:
            return self._options[id]

        raise Error('Unknown option %s.' % repr(id))

    def __setitem__(self, id, value):
        self._options[id] = value

    def set_default(self, id, value):
        if id not in self:
            self[id] = value

    def __iter__(self):
        for id in sorted(self._options):
            yield (id, self._options[id])

    def load(self, path):
        with open(path, 'rt') as f:
            for id, value in eval(f.read()).items():
                self[id] = value

    def save(self, path):
        tmp_path = path + '.tmp'
        with open(tmp_path, 'wt') as f:
            f.write('{\n')
            for id, value in self:
                f.write('    %s: %s,\n' % (repr(id), repr(value)))
            f.write('}\n')
        os.rename(tmp_path, path)


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

        self._config = dict()

        self._installed = False
        self._started = False

    def configure(self, config):
        if self._installed:
            raise Error('MariaDB shall be configured before installing.')

        for option, value in config.items():
            if option not in self._config:
                self._config[option] = value
                continue

            if self._config[option] != value:
                raise Error('Conflicting values for MariaDB option %s: %s and %s' % (
                                option, self._config[option], value))

    def _install_config_file(self):
        lines = ['', '[mysqld]']
        for option, value in self._config.items():
            lines.append('%s = %s' % (option, value))
        lines.append('')

        self.shell.write_file('/etc/mysql/mariadb.conf.d/99-custom_config.cnf',
                              '\n'.join(lines).encode('utf-8'))

    def install(self):
        self.system.update_upgrade()
        self.system.install_packages(['mariadb-server'])

        self._install_config_file()

        self._installed = True

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

    def stop(self):
        if self._started:
            self._manage('stop')
            self._started = False


class Apache2(object):
    def __init__(self, system):
        self.system = system
        self.shell = system.shell
        self.log = system.log

        self._config_dir = posixpath.join('/etc', 'apache2')
        self._sites_available_dir = posixpath.join(self._config_dir,
                                                   'sites-available')

        self._sites = dict()

        self._installed = False
        self._started = False

    def add_site(self, id, config):
        if self._installed:
            raise Error('Cannot add site %s: Apache2 is already installed.' % (
                            repr(id)))

        if id in self._sites:
            raise Error('Site %s already exists.' % repr(id))

        self._sites[id] = config

    def _generate_directive_lines(self, directives):
        return ['    %s %s' % d for d in directives]

    def _generate_site_config_file(self, config):
        lines = []
        for addr, directives in config['hosts'].items():
            lines.extend(['', '<VirtualHost %s>' % addr])
            lines.extend(self._generate_directive_lines(directives))
            lines.extend(['</VirtualHost>'])

        for path, directives in config['directories'].items():
            lines.extend(['', '<Directory "%s">' % path])
            lines.extend(self._generate_directive_lines(directives))
            lines.extend(['</Directory>'])

        lines.extend([''])

        return '\n'.join(lines).encode('utf-8')

    def _install_site_config_file(self, id, config):
        path = posixpath.join(self._sites_available_dir, '%s.conf' % id)
        self.shell.write_file(path, self._generate_site_config_file(config))

    def _enable_site(self, id):
        self.shell.run(['a2ensite', id])

    def _disable_site(self, id):
        self.shell.run(['a2dissite', id])

    def _disable_default_site(self):
        self._disable_site('000-default')

    def install(self):
        self.log('Install Apache2.')
        self.system.update_upgrade()
        self.system.install_packages(
            ['apache2',
             'libapache2-mod-php',  # TODO: Not all setups need this.
            ])

        self.shell.run('a2enmod rewrite')  # TODO: Not all setups need this.

        for id, config in self._sites.items():
            self._install_site_config_file(id, config)

        self._disable_default_site()

        for id in self._sites:
            self._enable_site(id)

        self._installed = True

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


class PHP(object):
    def __init__(self, system):
        self.system = system
        self.shell = system.shell
        self.log = system.log

        self._config = dict()

        self._installed = False

    def configure(self, config):
        if self._installed:
            raise Error('PHP shall be configured before installing.')

        for option, value in config.items():
            if option not in self._config:
                self._config[option] = value
                continue

            if self._config[option] != value:
                raise Error('Conflicting values for PHP option %s: %s and %s' % (
                                option, self._config[option], value))

    def _update_config_file(self):
        config_file_path = '/etc/php/7.2/apache2/php.ini'
        for option, value in self._config.items():
            self.shell.run(
                'sed -i -r "/%s ?=/{ s#.*#%s = %s# }" %s' % (
                    option.replace('.', r'\.'), option, value,
                    config_file_path))

    def install(self):
        self.log('Install PHP.')
        self.system.update_upgrade()

        self.system.install_packages(
            ['php',
             'php-mysql',  # Not all setups need these packages.
             'php-gd',
             'php-curl',
             'php-apcu',
             'php-cli',
             'php-json',
             'php-mbstring'])

        self._update_config_file()

        self._installed = True


class Phabricator(object):
    def __init__(self, mysql, webserver, php, config=Config()):
        self.mysql = mysql
        self.webserver = webserver
        self.php = php
        self.system = _identical(self.mysql.system, self.webserver.system,
                                 self.php.system)
        self.shell = self.system.shell
        self.log = self.mysql.log

        self._config = config

        # Shall be unique among all applications we support.
        self._config.set_default('app.id', 'phabricator')

        self._config.set_default('app.domain-base', 'dev.local')
        self._config.set_default('app.domain-files', 'devfiles.local')

        self._config.set_default('mysql.user.name',
                                 '%s_mysql_user' % self._config['app.id'])
        self._config.set_default('mysql.user.password',
                                 generate_password())

        self._config.set_default('app.daemon.user.name',
                                 '%s_user' % self._config['app.id'])

        self._config.set_default('app.site.id',
                                 '%s_site' % self._config['app.id'])

        self._app_path = posixpath.join('/opt', self._config['app.id'])
        self._phabricator_path = posixpath.join(self._app_path, 'phabricator')
        self._webroot_path = posixpath.join(self._phabricator_path, 'webroot')
        self._arcanist_path = posixpath.join(self._app_path, 'arcanist')
        self._libphutil_path = posixpath.join(self._app_path, 'libphutil')

        self._components = [
            ('libphutil', self._libphutil_path),
            ('arcanist', self._arcanist_path),
            ('phabricator', self._phabricator_path),
        ]

        self.mysql.configure({
            'sql_mode': 'STRICT_ALL_TABLES',

            # Size of the memory area where InnoDB caches table
            # and index data. Actually needs 10% more than
            # specified for related cache structures. Phabricator
            # whines if this is set to less than 256M. MySQL
            # won't start if it cannot allocate the specified
            # amount of memory with this error:
            #
            #     InnoDB: Fatal error: cannot allocate memory for
            #     the buffer pool
            #
            # This happened with 400M pool size (with apache and
            # phd daemons running).
            'innodb_buffer_pool_size': '1600M',

            'max_allowed_packet': '33554432',
        })

        self.webserver.add_site(self._config['app.site.id'], {
            'hosts': {
                '*': [
                    ('ServerName', self._config['app.domain-base']),
                    ('DocumentRoot', self._webroot_path),
                    ('RewriteEngine', 'on'),
                    ('RewriteRule', '^(.*)$ /index.php?__path__=$1 [B,L,QSA]'),
                ],
            },
            'directories': {
                self._webroot_path: [
                    ('Require', 'all granted'),
                ],
            },
        })

        self.php.configure({
            'date.timezone': "'Etc/UTC'",
            'post_max_size': '32M',

            # OPcache should be configured to never revalidate code.
            'opcache.validate_timestamps': '0',
        })

        self._daemon_started = False

    def get_config(self):
        return self._config

    def _run_config_set(self, id, value):
        config_path = posixpath.join(self._phabricator_path, 'bin', 'config')
        self.shell.run([config_path, 'set', id, value])

    def _run_storage(self, args):
        storage_path = posixpath.join(self._phabricator_path, 'bin', 'storage')
        self.shell.run([storage_path] + args)

    def install(self):
        self.system.update_upgrade()

        # Set up MySQL.
        self.mysql.install()

        self.log('Create the Phabricator MySQL user.')
        # https://coderwall.com/p/ne1thg/phabricator-mysql-permissions
        self.mysql.add_user(
            user=self._config['mysql.user.name'],
            password=self._config['mysql.user.password'],
            privileges='SELECT, INSERT, UPDATE, DELETE, EXECUTE, SHOW VIEW',
            objects='\`phabricator\_%\`.*')

        # Set up webserver.
        self.webserver.install()

        # Set up PHP.
        self.php.install()

        # Set up Phabricator.
        self.log('Create Phabricator application user.')


        ''' TODO
    dbg "Creating a user for Phabricator's files: $PH_USER"
    useradd -m ${PH_USER} -s /bin/bash && c=0 || c=$?
    # Ignore exit code 9 (user already exists), otherwise fail
    test $c -eq 0 -o $c -eq 9 || exit $c
        '''

        self.log('Install packages Phabricator relies on.')
        # https://secure.phabricator.com/source/phabricator/browse/master/scripts/install/install_ubuntu.sh
        # https://gist.github.com/sparrc/b4eff48a3e7af8411fc1
        self.system.install_packages(
            ['git',
             'mercurial',
             'subversion',
             'python-pygments',
             # 'sendmail',  # TODO: Do we need it?
             'imagemagick'])

        self.log("Retrieve phabricator components.")
        for component_name, path in self._components:
            dir = posixpath.dirname(path)
            if not self.shell.does_file_exist(path):
                self.shell.run(
                    'mkdir -p %s && '
                    'cd %s && '
                    'git clone https://github.com/phacility/%s.git' % (
                        dir, dir, component_name))
            else:
                self.shell.run(
                    'cd %s && '
                    'git pull' % path)

        self.log("Set up Phabricator MySQL user credentials.")
        self._run_config_set('mysql.user', self._config['mysql.user.name'])
        self._run_config_set('mysql.pass', self._config['mysql.user.password'])

        self.log('Configure Phabricator base and file URIs.')
        self._run_config_set('phabricator.base-uri',
                             "'http://%s/'" % self._config['app.domain-base'])
        self._run_config_set('security.alternate-file-domain',
                             "'http://%s/'" % self._config['app.domain-files'])

        self.log('Enable Pygments.')
        self._run_config_set('pygments.enabled', 'true')

        self.log('Configure Phabricator mail adapter.')
        self._run_config_set('metamta.mail-adapter',
                             'PhabricatorMailImplementationPHPMailerAdapter')

        self.log('Set up Phabricator repositories directory.')
        self.shell.run('mkdir -p /opt/repos')
        self._run_config_set('repository.default-local-path', '/opt/repos')

        self.log('Set up Phabricator files directory.')
        self.shell.run('mkdir -p /opt/files')
        self.shell.run('chown -R www-data:www-data /opt/files')
        self._run_config_set('storage.local-disk.path', '/opt/files')

        self.log('Set up MySQL Schema.')
        # TODO: Have a password for the root MySQL user.
        self._run_storage(['upgrade', '--force', '--user', 'root'])

        self.restart()

        self.shell.run('ps aux')

    def upgrade():
        # TODO
        # https://secure.phabricator.com/book/phabricator/article/upgrading/
        raise Error('Upgrading Phabricator is not supported yet.')

    def _manage_daemon(self, action):
        phd_path = posixpath.join(self._phabricator_path, 'bin', 'phd')
        self.shell.run([phd_path, action])

    def _start_daemon(self):
        self._restart_daemon()

    def _restart_daemon(self):
        self._manage_daemon('restart')
        self._daemon_started = True

    def _stop_daemon(self):
        if self._daemon_started:
            self._manage_daemon('stop')
            self._daemon_started = False

    def start(self):
        self.mysql.start()
        self._start_daemon()
        self.webserver.start()

    def restart(self):
        self.mysql.restart()
        self._restart_daemon()
        self.webserver.restart()

    def stop(self):
        self.webserver.stop()
        self._stop_daemon()
        self.mysql.stop()


def main():
    config = Config()
    config.load('config')

    try:
        local_shell = LocalShell(Logger())
        docker_shell = DockerContainerShell(container_name='phabricator',
                                            shell=local_shell)
        system = Ubuntu(docker_shell)
        phab = Phabricator(mysql=MariaDB(system),
                           webserver=Apache2(system),
                           php=PHP(system),
                           config=config)

        phab.install()
        phab.start()
    finally:
        config.save('config')


if __name__ == '__main__':
    main()
