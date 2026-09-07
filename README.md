# Showberry 🍓

An elegant, modern movie and TV series streaming application for GNOME built with Python, GTK 4, Libadwaita, MPV, and Libtorrent.

## Features

- **Rich Catalog**: Browse trending, popular, top-rated movies and TV series powered by TMDB.
- **Instant Search**: Debounced search with fast results across movies and series.
- **Multiple Providers & Torrent P2P**: High-speed direct streaming and sequential torrent playback with background buffering, metadata atom prefetching, and disk caching.
- **Hardware-Accelerated MPV**: Smooth OpenGL playback (`GSK_RENDERER=gl`) with fine-grained subtitle synchronization and custom track selection.
- **Continuous Resume**: Remembers exact watch progress and automatically resumes cached torrent releases without re-downloading pieces.
- **Clean Keyboard Navigation**: Full directional navigation, shortcuts for stream selection (`t`), stream buffer stats (`i`), subtitle menu (`s`), and tab switching.
- **Adaptive Libadwaita Interface**: Fits beautifully on desktop, mobile, and wide displays.

## Keyboard Shortcuts

### Player Controls
| Shortcut | Action |
| :--- | :--- |
| `Space` / `k` | Play / Pause |
| `Left` / `Right` | Seek backward / forward 10s |
| `Shift` + `Left` / `Right` | Seek backward / forward 1m |
| `Up` / `Down` | Volume up / down 5% |
| `m` | Mute / Unmute |
| `f` / `F11` | Toggle Fullscreen |
| `s` | Subtitles Menu & Timing |
| `z` / `x` | Adjust Subtitle Delay (-/+ 100ms) |
| `t` | Choose Torrent Release |
| `i` | Stream Details & Buffer Stats |
| `Esc` / `Backspace` | Exit Player / Go Back |

### Navigation
| Shortcut | Action |
| :--- | :--- |
| `Ctrl + 1` | Switch to Library (Watchlist & History) |
| `Ctrl + 2` | Switch to Movies |
| `Ctrl + 3` | Switch to Series |
| `Ctrl + Tab` / `Ctrl + Shift + Tab` | Next / Previous Tab |
| `/` or `Ctrl + F` | Quick Search |
| `w` | Toggle Watchlist for selected card |
| `Return` | Open Title Details |

## Installation & Running

### Run Directly (Development)
```bash
./run.sh
```

### Build & Install with Arch Linux / EndeavourOS PKGBUILD
```bash
makepkg -si
```

### Build with Flatpak
```bash
flatpak-builder --user --install --force-clean build-dir data/com.github.kinema.Kinema.json
```

## License
GPL-3.0-or-later
