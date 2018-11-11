#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import setuptools

setuptools.setup(
    name='wheelcode',
    version='1.0a0',
    packages=[],
    scripts=['wheelcode.py'],
    install_requires=[],
    description='Web applications deployment and maintenance library',
    author='Ivan Kosarev',
    author_email='ivan@kosarev.info',
    license='MIT',
    keywords='web server application deployment maintenance',
    url='https://github.com/kosarev/wheelcode',
    # TODO
    # entry_points={
    #     'console_scripts': [
    #         'tproc = tproc:main',
    #     ],
    # },
    # test_suite='tests',
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Environment :: Console',
        'Intended Audience :: Information Technology',
        'Intended Audience :: System Administrators',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 3',
        'Topic :: Internet',
        'Topic :: Internet :: WWW/HTTP',
        'Topic :: Internet :: WWW/HTTP :: Site Management',
    ],
)
