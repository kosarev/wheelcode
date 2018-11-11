# wheelcode
Web applications deployment and maintenance library


## Design notes

* Services and applications are represented as Pytnon objects.

* The services applications depend on are passed to application
objects on initialization (the `__init__()` method).
Thus service objects may be shared between several applications.

* As application objects initialize, they instruct the service
objects they depend on regarding desired configuration.
It is the responsibility of the service object to catch and
diagnose configuration requests that can't be satisfied.

* Once all service and application objects are initialized, their
configurations are considered consistent.
