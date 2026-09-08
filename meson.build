project(
  'showberry',
  version: '0.1.1',
  meson_version: '>= 0.62',
  default_options: [
    'warning_level=2',
  ],
)

i18n = import('i18n')
python = import('python').find_installation('python3')

base_dir = meson.current_source_dir()
showberry_dir = base_dir / 'showberry'

# Install Python sources
install_subdir(
  'showberry',
  install_dir: python.get_install_dir(),
)

# Install CSS stylesheet
install_data(
  'data/style.css',
  install_dir: get_option('datadir') / 'showberry',
)

# Compile GSettings schema
install_data(
  'data/io.github.Dackerie.Showberry.gschema.xml',
  install_dir: get_option('datadir') / 'glib-2.0' / 'schemas',
)

# Compile GSettings schema
meson.add_install_script(
  'glib-compile-schemas',
  get_option('prefix') / get_option('datadir') / 'glib-2.0' / 'schemas',
)

# Install desktop file
install_data(
  'data/io.github.Dackerie.Showberry.desktop',
  install_dir: get_option('datadir') / 'applications',
)

# Install AppStream metainfo
install_data(
  'data/io.github.Dackerie.Showberry.metainfo.xml',
  install_dir: get_option('datadir') / 'metainfo',
)

# Install icons
install_subdir(
  'data/icons',
  install_dir: get_option('datadir') / 'icons',
)

# Create run script
run_script = """
#!/bin/sh
exec python3 @0@/showberry/main.py
""".format(base_dir)

meson.add_install_script(
  'sh', '-c',
  'mkdir -p @0@/bin && echo \'@1@\' > @0@/bin/showberry && chmod +x @0@/bin/showberry'.format(
    get_option('prefix'),
    run_script.strip(),
  ),
)
