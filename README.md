<img height="128" src="data/app.drey.Dialect.svg" align="left"/>

# Dialect + Ollama

A fork of [Dialect](https://github.com/dialect-app/dialect), the GNOME translation app, with local English ↔ Ukrainian translation through [Ollama](https://ollama.com/). The original translation providers remain available.

![Dialect](preview.png?raw=true)

## Translation Providers

- Local AI: **Ollama** — English ↔ Ukrainian with a locally installed model and a configurable endpoint.
- Proprietary:
    - [Google Translate](https://translate.google.com/)
    - [DeepL](https://www.deepl.com/en/translator) - Requires a Free or Paid API key.
    - [Kagi Translate](https://translate.kagi.com/) - Requires session token (not complete URL) from [Kagi settings](https://kagi.com/settings/user_details) as API Key.
    - [Microsoft Translator (Bing)](https://www.bing.com/translator)
    - [Yandex Translate](https://translate.yandex.com/)
- Open Source:
    - LibreTranslate - Use any public instance, defaults to [our own](https://lt.dialectapp.org/).
    - Lingva Translate - Use any public instance, defaults to [our own](https://lingva.dialectapp.org/).

## Features

- Translation history
- Automatic language detection
- Text to speech
- Clipboard buttons
- Local file translation with supported text and document formats
- Optional Ollama model preload, keep-alive, and unload on exit

## Installation

The package links below install upstream Dialect and **do not include this fork's Ollama provider**. Build this fork from source to use Ollama.

### Flathub

<a href='https://flathub.org/apps/details/app.drey.Dialect'><img alt='Download on Flathub' src='https://flathub.org/api/badge?svg&locale=en'/></a>

### Arch Linux

The stable version is available from the official `Extra` repository: [`dialect`](https://archlinux.org/packages/extra/any/dialect/) and the latest git revision is available as an AUR package: [`dialect-git`](https://aur.archlinux.org/packages/dialect-git/)

### Fedora

Dialect is available for Fedora 33 and later:

```bash
sudo dnf install dialect
```

### Debian

Dialect is available in Debian 12 and later:

```bash
sudo apt-get install dialect
```

## Build and install this fork from source

### Requirements

- Python 3 (>=3.10) `python`
- PyGObject (>=3.51.0) `python-gobject`
- GTK4 (>= 4.17.5) `gtk4`
- libadwaita (>= 1.7.0) `libadwaita`
- libsoup (>= 3.0) `libsoup`
- libsecret
- libspelling
- GStreamer 1.0 `gstreamer`
- Meson `meson`
- Ninja `ninja`
- gTTS `python-gtts`
- Beautiful Soup `python-beautifulsoup4`
- `blueprint-compiler`
- `gettext`
- `pkg-config`

Install these dependencies with your distribution's package manager before running Meson. Package names vary by distribution; the names above are a guide. Meson checks the required GTK, libadwaita, PyGObject, and other library versions during setup. The Python dependencies are also listed in `requirements.txt`. If your distribution does not package gTTS or Beautiful Soup, install them into the Python environment used to run Dialect:

```bash
python3 -m pip install gtts beautifulsoup4
```

### Build and install system-wide

```bash
git clone https://github.com/0xra0/dialect.git
cd dialect
meson setup builddir --prefix=/usr/local
meson compile -C builddir
sudo meson install -C builddir
dialect
```

If you already have this source directory, begin with `meson setup` inside it and skip the clone commands. A system install may replace an existing `/usr/local` Dialect installation. Run `dialect` from a terminal or launch it from the desktop application menu after installation.

### Build and run without installing system-wide

For development, install to a directory inside the build tree and use Meson's run target:

```bash
git clone https://github.com/0xra0/dialect.git
cd dialect
meson setup builddir --prefix="$(pwd)/builddir/testdir"
meson compile -C builddir
meson install -C builddir
meson compile -C builddir run
```

The local build needs the same runtime libraries and Python modules listed above. To rebuild after changes, run `meson compile -C builddir` again.

## Contributing

Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.

### Translations

Dialect has already been translated into many languages (see the [translations repository](https://github.com/dialect-app/po/blob/main/README.md) file). Please help translate Dialect into more languages through [Weblate](https://hosted.weblate.org/engage/dialect/).

<a href="https://hosted.weblate.org/engage/dialect/">
<img src="https://hosted.weblate.org/widgets/dialect/-/dialect/multi-auto.svg" alt="Translation status" />
</a>

## License

[GNU General Public License 3 or later](https://www.gnu.org/licenses/gpl-3.0.en.html)

## Ollama local translation

1. Install and start [Ollama](https://ollama.com/download) on your machine. Its default API endpoint is `http://localhost:11434`.
2. Install a model in Ollama. The provider defaults to `gemma4-hauhau-uk`, a custom model name; if that model is not installed, select an installed model in Dialect's provider settings. Check available names with `ollama list`.
3. In Dialect, open **Preferences → Translation Provider** and select **Ollama (Local AI)**. In its provider settings, set the model name and, if needed, the Ollama endpoint.
4. Choose English and Ukrainian as source and target languages. Automatic detection distinguishes these two languages only.

The provider uses Ollama's `/api/generate` endpoint. It accepts both an untagged model name and the equivalent `:latest` name shown by Ollama. Text is sent to the configured Ollama endpoint; with the default endpoint, it stays on your own machine. If you configure a remote endpoint, that server receives the text.

Ollama settings in **Preferences** can preload the model in the background, keep it loaded while Dialect is open, and unload it when Dialect exits. These switches are enabled by default. The provider also offers a thinking switch; it is off by default for faster translation.

The bundled `ModelFile` is an example from one local setup and contains an absolute `FROM` path. It is not a portable model download or a prerequisite for using the provider.

## About this fork

This repository adds Ollama integration to [upstream Dialect](https://github.com/dialect-app/dialect). For upstream releases, packages, translations, and general project information, see the upstream project. This fork is licensed under the same [GPL-3.0-or-later license](LICENSE).
