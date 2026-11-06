# Base justfile — intentionally minimal.
#
# All workflow recipes (install, lint, test, format, update, clean, coverage,
# ci-*) live in .justfile.<name> files pulled in via `import?`.

# The project's own recipes come first. ~/.justfile allows a recipe or variable twice and
# keeps the first definition, so naming one of its recipes again overrides it. An imported
# recipe stays unique: without ~/.justfile, a second definition does not parse.
import? '.justfile.downlink'
import? '~/.justfile'
import? '.justfile.django'
import? '.justfile.package'
import? '.justfile.library'
import? '.justfile.meta'

@_default:
    just --list
