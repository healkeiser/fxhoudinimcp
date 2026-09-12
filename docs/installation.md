# :material-download:{.scale-in-center} Installation

--8<-- "README.md:installation"

## Optional Dependencies

### Documentation

The site is built with [Zensical](https://zensical.org/). To build it locally:

``` shell
pip install -r requirements.docs.txt
python docs/.scripts/generate_technical_docs.py
python -m zensical serve
```

The first line also installs the fork of `mike` that Zensical uses for
versioned deploys; `pip install -e ".[docs]"` alone skips it. The second
writes the Technical section into `docs/technical/` (gitignored) from the
Python package, since Zensical has no gen-files plugin.
