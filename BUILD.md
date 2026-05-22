# Build notes

This is for building notes for the developer.

Do normal git's on a dev branch:
```
git switch -c dev
```

Mark version like 0.2.0.dev0 where 0.2.0 is non-existing next version.

When dev branch is ready?

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

Then Merge Dev to main.

then publish to PyPi. Tagging should happen on main branch, not dev.
```
git tag v0.1.0
git push --tags
uv publish
```

