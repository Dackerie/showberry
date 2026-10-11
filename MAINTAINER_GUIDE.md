# Showberry Maintainer & Developer Guide
*A plain-English handbook for maintaining, understanding, and improving Showberry.*

---

## Table of Contents
1. [Welcome: Demystifying Programming](#1-welcome-demystifying-programming)
2. [The 6 Core Programming Concepts (Without the Jargon)](#2-the-6-core-programming-concepts-without-the-jargon)
3. [The Big Picture: How Showberry Works](#3-the-big-picture-how-showberry-works)
4. [File-by-File Walkthrough: What Every File Does](#4-file-by-file-walkthrough-what-every-file-does)
   - [The Entryway & Window (How the App Starts)](#the-entryway--window)
   - [The UI Views (What You See on Screen)](#the-ui-views)
   - [The Services (The Brains Behind the Scenes)](#the-services)
   - [The Providers (How Streams Are Found)](#the-providers)
   - [The Styling & Assets](#the-styling--assets)
   - [The Test Suite (Your Safety Net)](#the-test-suite)
5. [The Maintainer's Diagnostic Playbook](#5-the-maintainers-diagnostic-playbook)
   - [Playbook 1: A Streaming Provider Stops Working](#playbook-1-a-streaming-provider-stops-working)
   - [Playbook 2: Changing Colors, Spacing, or Badges](#playbook-2-changing-colors-spacing-or-badges)
   - [Playbook 3: Adding a New Keyboard Shortcut](#playbook-3-adding-a-new-keyboard-shortcut)
   - [Playbook 4: How to Read a Python Crash Error (Traceback)](#playbook-4-how-to-read-a-python-crash-error-traceback)
6. [Curated Learning Roadmap: What to Learn & Where to Learn It](#6-curated-learning-roadmap-what-to-learn--where-to-learn-it)
7. [The Mental Shift: How to Use AI as Your Junior Assistant](#7-the-mental-shift-how-to-use-ai-as-your-junior-assistant)

---

## 1. Welcome: Demystifying Programming

If you built Showberry using AI and look at the code today, it can feel like looking at the cockpit of a Boeing 747: hundreds of switches, strange terms like `libsodium`, `Gtk.GLArea`, `ctypes`, and `Adw.NavigationView`.

Here is the secret that professional programmers rarely admit:
**You do not need to understand 100% of the code to maintain and improve it.**

* You don't need to know how the car's alternator is wound to change the oil or install a new stereo.
* In Showberry, 80% of what looks intimidating is just **plumbing**—moving text or numbers from one place (like an internet link or a database) to another place (a button or a video player).
* You already have something most beginners don't have: **a complete, working application with 180 automated tests** that check if everything is working in 8 seconds.

This guide is written to bridge the gap between "I don't know code" and "I can confidently change and fix Showberry."

---

## 2. The 6 Core Programming Concepts (Without the Jargon)

Everything in Showberry is built from six fundamental concepts. Once you understand these, you can read almost any file in the app:

### 1. Variables (Labeled Boxes)
A variable is simply a named box that stores a piece of information.
```python
movie_title = "Inception"      # Text (called a string)
release_year = 2010            # Number (called an integer)
is_favorite = True             # True or False (called a boolean)
```

### 2. Lists & Dictionaries (Organized Boxes)
* **A List** is an ordered checklist:
  ```python
  genres = ["Action", "Sci-Fi", "Thriller"]
  ```
* **A Dictionary** is a labeled folder with keys and values:
  ```python
  movie = {
      "title": "Inception",
      "rating": 8.8,
      "director": "Christopher Nolan"
  }
  # To get the director:
  print(movie["director"])  # prints: Christopher Nolan
  ```

### 3. Functions (Recipes)
A function is a reusable recipe. You give it ingredients (inputs), it performs steps, and gives you a result (output).
```python
def calculate_finish_time(runtime_minutes):
    now = datetime.now()
    finish = now + timedelta(minutes=runtime_minutes)
    return finish.strftime("%I:%M %p")
```

### 4. Classes & Objects (Cookie Cutters & Cookies)
* A **Class** is a blueprint (the cookie cutter).
* An **Object** is the real thing created from that blueprint (the cookie).
In Showberry, `MovieCard` is a class. In your catalog, when 20 movies appear on screen, the computer created 20 individual *objects* from that single `MovieCard` class, each holding its own poster and title.
* In Python, inside a class you will see `self`. `self` just means "my own". `self.title` means "this specific card's title".

### 5. Events & Signals (Doorbells)
In a desktop app, code doesn't just run from line 1 to line 100 and quit. The app sits quietly waiting for the user to do something.
When you click a button, the button rings a **signal** (like a doorbell).
You connect that signal to a function:
```python
# "When play_button is clicked, run self._on_play_clicked"
self.play_button.connect("clicked", self._on_play_clicked)
```

### 6. APIs (The Waiter at a Restaurant)
When Showberry needs movie information, it doesn't have every movie stored inside the app. It talks to **TMDB** (The Movie Database).
An **API** (Application Programming Interface) is like a waiter:
1. Showberry gives the waiter an order: *"Give me the popular movies for 2026"*.
2. The TMDB server prepares the data.
3. The waiter brings back a response formatted as JSON (which is just a Python dictionary with titles, summaries, and poster links).

---

## 3. The Big Picture: How Showberry Works

Showberry is divided into 5 distinct layers:

```
[User clicks a movie]
        │
        ▼
[1. UI Layer (showberry/ui/)]
   └─ Shows the poster, title, buttons, and handles mouse/keyboard events.
        │
        ▼
[2. Services (showberry/services/)]
   ├─ tmdb.py: Fetches descriptions, cast, and backdrops.
   ├─ database.py: Remembers watch progress ("watched 45 mins of 120 mins").
   └─ settings.py: Remembers your preferences (dark theme, subtitles).
        │
        ▼
[3. Providers (showberry/providers/)]
   └─ vidlink.py, vidsrc.py, etc.: Scrapes streaming sites to find the direct video URL.
        │
        ▼
[4. Video Player (showberry/ui/player_page.py)]
   └─ Uses libmpv to render hardware-accelerated video on screen.
```

---

## 4. File-by-File Walkthrough: What Every File Does

### The Entryway & Window
These files boot up the app and create the main window shell.

* **[showberry/main.py](file:///home/vishwam/code/showberry/showberry/main.py)** & **[showberry/__main__.py](file:///home/vishwam/code/showberry/showberry/__main__.py)**:
  * **Job**: The ignition switch. When you type `python3 -m showberry` or launch the app icon, this runs first.
  * **What it does**: Sets up system graphics (enabling OpenGL hardware acceleration), checks whether you are on Linux or Windows, and starts the GTK Application.
  * **When to touch it**: Rarely. Only if changing command-line flags or startup environment variables.

* **[showberry/application.py](file:///home/vishwam/code/showberry/showberry/application.py)**:
  * **Job**: The application manager singleton.
  * **What it does**: Handles app identity (`io.github.Dackerie.Showberry`), loads the user settings schema, and opens the main window when you launch the app.
  * **When to touch it**: If you need app-wide actions like handling file associations or command-line URLs.

* **[showberry/window.py](file:///home/vishwam/code/showberry/showberry/window.py)**:
  * **Job**: The main outer window frame.
  * **What it does**: Creates the top header bar, the search bar shortcut (`/`), the hamburger menu, and the view switcher tabs at the bottom/top. It holds the `Adw.ViewStack` that switches between the **Library**, **Movies**, and **TV Series** tabs.
  * **When to touch it**: If you want to add a brand new main tab (like "Anime" or "Favorites"), or change window-wide keyboard shortcuts.

---

### The UI Views
Everything inside `showberry/ui/` is what you see and interact with.

* **[showberry/ui/movie_card.py](file:///home/vishwam/code/showberry/showberry/ui/movie_card.py)**:
  * **Job**: The individual poster cards in the grid.
  * **What it does**: Downloads and caches the poster image, renders the title, calculates runtime, displays status badges (`IN THEATERS`, `UPCOMING`, `NETFLIX`, `HBO`), and shows the circular hover play button.
  * **When to touch it**: To change card sizes, tweak badge labels, or adjust hover animations.

* **[showberry/ui/movies_page.py](file:///home/vishwam/code/showberry/showberry/ui/movies_page.py)** & **[showberry/ui/series_page.py](file:///home/vishwam/code/showberry/showberry/ui/series_page.py)**:
  * **Job**: The browse catalogues for movies and television.
  * **What it does**: Creates the multi-column grid of movie cards, requests pages from TMDB as you scroll down (infinite scroll), and provides the filter menu (by genre, year, rating).
  * **When to touch it**: To change default sorting (e.g. Popular vs Top Rated) or adjust grid spacing.

* **[showberry/ui/library_page.py](file:///home/vishwam/code/showberry/showberry/ui/library_page.py)**:
  * **Job**: Your personal home tab.
  * **What it does**: Displays the "Continue Watching" carousel (showing red progress bars for partially watched movies/shows) and your custom "Watchlist".
  * **When to touch it**: To modify how watch progress is displayed or add a "Completed" shelf.

* **[showberry/ui/movie_page.py](file:///home/vishwam/code/showberry/showberry/ui/movie_page.py)**:
  * **Job**: The movie/TV details page.
  * **What it does**: Loads the high-resolution backdrop image, shows the tagline, summary, cast avatars, director chip, recommendations row, and the big "Play" button. For TV shows, it renders the season dropdown and episode list.
  * **When to touch it**: To add new movie metadata fields (e.g. budget, revenue, age rating).

* **[showberry/ui/player_page.py](file:///home/vishwam/code/showberry/showberry/ui/player_page.py)**:
  * **Job**: The full-screen video player.
  * **What it does**: Embeds `libmpv` inside an OpenGL area (`Gtk.GLArea`). Houses the on-screen frosted-glass control bar, timeline seekbar, audio track selector popover, subtitle download menu, playback speed selector, and volume boost.
  * **When to touch it**: To change player keyboard shortcuts (like `Space` to pause, `Left/Right` to seek), adjust timeline behavior, or tweak subtitle styles.

* **[showberry/ui/settings_page.py](file:///home/vishwam/code/showberry/showberry/ui/settings_page.py)**:
  * **Job**: The Preferences window.
  * **What it does**: Lets the user configure their TMDB API key, toggle dark mode, prioritize streaming providers, enable torrent streaming, and check for updates.
  * **When to touch it**: When adding a new user-customizable option.

* **[showberry/ui/stream_dialogs.py](file:///home/vishwam/code/showberry/showberry/ui/stream_dialogs.py)**:
  * **Job**: The stream picker modal.
  * **What it does**: When you click Play, this modal shows the loading spinner, queries providers in priority order, tests which stream links are healthy, and lets the user choose between providers/qualities.
  * **When to touch it**: To change timeout limits or modify how stream qualities (1080p, 720p) are listed.

---

### The Services
The files in `showberry/services/` contain the pure logic and data storage.

* **[showberry/services/tmdb.py](file:///home/vishwam/code/showberry/showberry/services/tmdb.py)**:
  * **Job**: Talks to the TMDB API.
  * **What it does**: Has functions like `get_trending_movies()`, `get_movie_details(tmdb_id)`, `search(query)`. Formats web addresses, sends HTTP requests with `requests`, and parses the JSON response.
  * **When to touch it**: If you want to fetch new data from TMDB (e.g., trailers, reviews).

* **[showberry/services/database.py](file:///home/vishwam/code/showberry/showberry/services/database.py)**:
  * **Job**: Local SQLite storage.
  * **What it does**: Creates the database file `~/.local/share/showberry/showberry.db`. It stores:
    * `watch_history`: movie ID, current timestamp, duration, last watched date.
    * `watchlist`: saved items.
  * **When to touch it**: When you need Showberry to remember a new piece of persistent information (e.g. marking a show as "favorite").

* **[showberry/services/settings.py](file:///home/vishwam/code/showberry/showberry/services/settings.py)**:
  * **Job**: App configuration manager.
  * **What it does**: Reads and writes settings (like `theme`, `default-quality`, `provider-order`). Uses GNOME GSettings when available, with a graceful fallback to a local JSON file.
  * **When to touch it**: Whenever you create a new configuration option.

* **[showberry/services/subtitles.py](file:///home/vishwam/code/showberry/showberry/services/subtitles.py)**:
  * **Job**: Subtitle search and downloader.
  * **What it does**: Queries the OpenSubtitles API for subtitle tracks matching the movie or TV show, downloads the `.srt` or `.vtt` file, and gives it to MPV.

* **[showberry/services/torrent.py](file:///home/vishwam/code/showberry/showberry/services/torrent.py)**:
  * **Job**: P2P sequential torrent streamer.
  * **What it does**: Downloads torrent video pieces sequentially (first minute first, last minute next) and serves them locally to MPV over an internal HTTP port.

* **[showberry/services/image_cache.py](file:///home/vishwam/code/showberry/showberry/services/image_cache.py)**:
  * **Job**: Poster & backdrop disk cache.
  * **What it does**: Saves downloaded movie posters to disk so Showberry doesn't re-download them every time you open the app.

---

### The Providers
The files in `showberry/providers/` are web scrapers that discover playable stream URLs.

* **[showberry/providers/base.py](file:///home/vishwam/code/showberry/showberry/providers/base.py)**:
  * **Job**: The master blueprint.
  * **What it does**: Defines `StreamResult` (the result box holding `url`, `quality`, and `headers`) and `BaseProvider`. Every individual provider inherits from `BaseProvider` and must implement `get_stream_url(tmdb_id, season, episode)`.
  * Also contains `is_stream_alive(res)` to verify that a stream URL is working before handing it to the player.

* **Individual Scrapers (`vidlink.py`, `vidsrc.py`, `cinejoy.py`, etc.)**:
  * **Job**: Visiting streaming host pages and extracting the `.m3u8` video playlist link.
  * *Don't be intimidated by the cryptographic parts!* In files like `vidlink.py`, you may see references to `libsodium` or `XSalsa20`. That is simply because that specific provider encrypts their link to prevent unauthorized scraping. If that provider breaks, you don't need to invent crypto—you can simply disable that provider or look at open-source scraper communities (such as Consumet) to see how others updated the URL.

---

### The Styling & Assets
* **[showberry/data/style.css](file:///home/vishwam/code/showberry/showberry/data/style.css)**:
  * **Job**: The visual presentation stylesheet.
  * **What it does**: Written in standard CSS (Cascading Style Sheets). Controls colors, rounded corners (`border-radius`), padding, translucent frosted-glass backgrounds (`rgba(0, 0, 0, 0.6)`), and font sizes for badges.
  * **When to touch it**: Whenever you want to restyle the interface!

---

### The Test Suite
The files in `tests/` are automated verification scripts.

* **[tests/test_database.py](file:///home/vishwam/code/showberry/tests/test_database.py)**: Verifies that saving and loading watch history from SQLite works properly.
* **[tests/test_ui_navigation.py](file:///home/vishwam/code/showberry/tests/test_ui_navigation.py)**: Verifies that clicking tabs, movie cards, and buttons navigates to the right pages without crashing.
* **[tests/test_providers.py](file:///home/vishwam/code/showberry/tests/test_providers.py)**: Verifies provider URL formatting and stream validation.

To run all 180 tests right now:
```bash
pytest -v
```
If you make a change to the code and `pytest` gives 180 green passes, you can be 99% confident you didn't break the application!

---

## 5. The Maintainer's Diagnostic Playbook

### Playbook 1: A Streaming Provider Stops Working
This is the most common real-world maintenance task for media apps.

1. **Test the providers**:
   Run the provider test suite to see which provider is failing:
   ```bash
   pytest tests/test_providers.py -v
   ```
2. **Run in Debug Mode**:
   Launch Showberry with debug logging enabled to see live network output:
   ```bash
   python3 -m showberry --debug
   ```
3. **Inspect the provider file**:
   Open the failing provider file in `showberry/providers/<name>.py`.
   Check the `base_url`. Often, streaming sites simply change their domain (e.g. from `.to` to `.cc` or `.pro`).
4. **Inspect in your Web Browser**:
   Open the streaming site in Firefox or Chrome.
   Press `F12` to open **Developer Tools** and switch to the **Network** tab.
   Type `.m3u8` in the filter box.
   Play a video on the site. You will see the exact network request where the browser fetches the stream. Compare that request URL to what is written in your Python scraper!

---

### Playbook 2: Changing Colors, Spacing, or Badges
Want to change the color of the `IN THEATERS` badge?

1. Open [showberry/ui/movie_card.py](file:///home/vishwam/code/showberry/showberry/ui/movie_card.py).
2. Search for `IN THEATERS`. You'll see:
   ```python
   if media_type == 'movie' and 0 <= days_ago <= 60:
       return 'IN THEATERS'
   ```
3. Now open [showberry/data/style.css](file:///home/vishwam/code/showberry/showberry/data/style.css).
4. Search for the CSS class attached to that badge (e.g. `.badge` or `.in-theaters`).
5. Change the background color, for example:
   ```css
   background-color: #e01b24; /* Red */
   ```
6. Run the app (`./run.sh`) to see your changes immediately.

---

### Playbook 3: Adding a New Keyboard Shortcut
Want to add a hotkey (e.g., pressing `m` to mute/unmute in the player)?

1. Open [showberry/ui/player_page.py](file:///home/vishwam/code/showberry/showberry/ui/player_page.py).
2. Search for `key-pressed` or `_on_key_pressed`. You will find the function that listens to keyboard inputs:
   ```python
   def _on_key_pressed(self, controller, keyval, keycode, state):
   ```
3. Inside this function, you'll see a series of checks:
   ```python
   if keyval == Gdk.KEY_space:
       self._toggle_pause()
       return True
   elif keyval == Gdk.KEY_f:
       self._toggle_fullscreen()
       return True
   ```
4. Simply add your new check:
   ```python
   elif keyval == Gdk.KEY_m:
       self._toggle_mute()
       return True
   ```
5. Save the file and test it!

---

### Playbook 4: How to Read a Python Crash Error (Traceback)
When something goes wrong, Python prints a message called a **Traceback**. Non-programmers often panic when seeing this wall of text.
**Always read from the bottom up!**

```text
Traceback (most recent call last):
  File "showberry/ui/movie_card.py", line 180, in _on_clicked
    self.emit('play-movie', self._movie_data['id'])
KeyError: 'id'
```

1. **The very last line (`KeyError: 'id'`)**: This tells you the exact problem. Python looked for a key named `'id'` inside the movie dictionary, but it wasn't there!
2. **The line right above (`showberry/ui/movie_card.py, line 180`)**: This gives you the exact file and line number where the problem occurred.
3. **The Fix**: Instead of blindly accessing `self._movie_data['id']`, you can write safe code using `.get()`:
   ```python
   movie_id = self._movie_data.get('id')
   if movie_id:
       self.emit('play-movie', movie_id)
   ```

---

## 6. Curated Learning Roadmap: What to Learn & Where to Learn It

You do not need to study everything at once. Follow this sequential, 4-stage learning path:

### Stage 1: The Basics of Python (2–3 Weeks)
* **Goal**: Understand variables, dictionaries, lists, functions, and reading simple scripts.
* **The Best Free Resource**: **[Python for Everybody (PY4E)](https://www.py4e.com/)** by Dr. Charles Severance.
  * Watch Chapters 1 through 10.
  * Dr. Chuck teaches with extreme clarity and assumes you have **zero** technical background.

### Stage 2: Classes & Object-Oriented Programming (1–2 Weeks)
* **Goal**: Understand `class`, `self`, `__init__`, and inheritance so that `showberry/ui/` and `showberry/providers/` make sense.
* **The Best Free Resource**: **[Corey Schafer's Python OOP Tutorials](https://www.youtube.com/playlist?list=PL-osiE80TeTsqhIuOqKhwlXsIBIdSeYtc)** on YouTube.
  * Watch videos 1 to 4 (about 15 minutes each).
  * This will demystify `self` and class inheritance once and for all.

### Stage 3: GTK 4 & Libadwaita Desktop Programming (2–3 Weeks)
* **Goal**: Understand buttons, boxes, stacks, signals, and how desktop apps are constructed.
* **The Best Free Resource**: **[Taiko2k's Python GTK4 Tutorial](https://github.com/Taiko2k/GTK4PythonTutorial)**.
  * Clone or read through the tutorials. It builds tiny GTK4 Python apps step-by-step from 10-line scripts to full applications.
* **Reference**: Bookmark **[PyGObject API Reference](https://lazka.github.io/pgi-docs/)** to search GTK methods whenever needed.

### Stage 4: Web APIs & SQLite (1–2 Weeks)
* **Goal**: Understand how HTTP requests fetch data from TMDB and how SQLite saves bookmarks.
* **Resources**:
  * **[SQLBolt (sqlbolt.com)](https://sqlbolt.com/)**: Free, 1-hour interactive browser tutorial for SQL queries (`SELECT`, `INSERT`, `UPDATE`).
  * **[MDN Web Docs: Inspecting Network Activity](https://developer.mozilla.org/en-US/docs/Learn/Common_questions/Tools_and_setup/What_are_browser_developer_tools)**: Learn how to open your browser's Network tab (`F12`) to inspect video streams.

---

## 7. The Mental Shift: How to Use AI as Your Junior Assistant

Now that you are learning the architecture of Showberry, your relationship with AI will transform.

* **Before (Non-programmer)**: *"AI, make this app for me and fix whatever is broken."*
  * Result: You receive hundreds of lines of mystery code that you don't understand and fear touching.
* **Now (Maintainer & Architect)**: *"AI, explain what lines 50-80 in `showberry/ui/movie_card.py` are doing"* or *"AI, help me write a function that formats minutes into hours and minutes, and show me how to test it with pytest."*

Use AI to:
1. **Explain specific code snippets**: Highlight 10 lines of code you find confusing and ask: *"Explain what these 10 lines do in plain English with an analogy."*
2. **Draft unit tests**: Ask AI to write a test for a specific function to make sure your edge cases are covered.
3. **Debug tricky errors**: Paste the exact Python traceback and the function it points to, and ask for a line-by-line explanation of why the crash happened.

With this guide in your repository, you now have the exact roadmap to master, maintain, and expand Showberry on your own terms. Happy hacking!
