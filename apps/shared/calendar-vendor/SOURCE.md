# Calendar recurrence dependencies

A source subset of python-dateutil 2.9.0.post0 provides RFC 5545 recurrence
expansion through its rrule constructor and rruleset. Its parser, timezone and
easter modules are not used. six 1.17.0 supplies compatibility imports.
These dependencies are bundled so dashboard refreshes do not install packages.
Original source files are unmodified and their licenses are included.

- python-dateutil: https://files.pythonhosted.org/packages/66/c0/0c8b6ad9f17a802ee498c46e004a0eb49bc148f2fd230864601a86dcf6db/python-dateutil-2.9.0.post0.tar.gz
  SHA-256: `37dd54208da7e1cd875388217d5e00ebd4179249f90fb72437e91a35459a0ad3`
- six: https://files.pythonhosted.org/packages/94/e7/b2c673351809dca68a0e064b6af791aa332cf192da575fd474ed7d6f16a2/six-1.17.0.tar.gz
  SHA-256: `ff70335d468e7eb6ec65b95b99d3a2836546063f63acc5171de367e834932a81`
