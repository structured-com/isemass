# Build notes

This is for building notes for the developer.

Test locally first:
```
uv tool uninstall isemass
uv tool install .
isemass -h
```

build with:
```
uv build --no-sources
```
this will create files in /dist/ accordingly for that version.

test wheel locally if desired (replace version accordingly):
```
uv tool uninstall isemass
uv tool install dist/isemass-0.1.0-py3-none-any.whl
isemass --help
```

then publish:
```
uv publish
```