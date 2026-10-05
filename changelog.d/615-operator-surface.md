### Changed

- **Every plan names its operator surface, and upgrade actions get their own line** (#615). A plan now carries an "Operator surface" line beside "Local baseline" and "Cheapest alternative", saying where the feature lands for the people running and using vinga: keys, concepts once they ship, task guides, readiness checks, device guides, or none. A changelog fragment whose change asks something of an operator ends with an `Upgrade:` line giving the exact commands, renamed keys and migration notes, written for someone upgrading across several merges who reads only those lines.
