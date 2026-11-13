# DeskSpace

Translucent fences and widgets for the Linux desktop. Sort your icons into fences, keep notes, a calendar and system stats on the desktop, launch your games from cover art, and share it all with a few small animals that wander along the tops of your fences.

Everything sits at desktop level, so it never covers your apps. Current version: **1.4.1**. Built with Python and PySide6. This branch is the Linux version, for Ubuntu, Linux Mint and other apt-based systems. The Windows version is on the [`windows-build`](../../tree/windows-build) branch.

## Features

### Fences

- **Icon fences:** drag desktop icons and files into a fence. Each fence is a real folder, so your files stay ordinary files.
- **Folder portals:** show any folder on your PC as a fence. Double-click a subfolder to open it right in the portal; the Up item, Backspace, the mouse's back button or a click on any folder in the title bar takes you back.
- **Sorting:** sort each fence by name, date modified, size or type, from its right-click menu or its settings. Folders stay first.
- **Tabs:** drag one fence onto another to combine them into a tab group.
- **Auto-sort:** sort the desktop into fences by file type in one go, or give a fence patterns like `*.xlsx` or `invoice*` so matching files move into it automatically.
- **Snapping:** fences snap to screen edges and to each other, with an adjustable distance.
- **Monitor setups:** fences remember where they were for each set of screens, and go back there when you plug in or remove a monitor.
- **Roll up:** double-click a title bar to collapse a fence.
- **Quick-hide:** double-click an empty spot on the desktop, or the tray icon, to hide all fences, and optionally the desktop icons too.
- **Appearance:** fence colours can follow your wallpaper, or you can pick your own. Title size is adjustable.
- **File previews:** hover over a file to see a thumbnail, or the first lines of a text file.

### Widgets

- **Sticky note** and **to-do list**
- **Clock and calendar:** shows upcoming events from an iCal link, such as Google Calendar or Outlook.com.
- **System monitor:** CPU, RAM, GPU, VRAM, network, disk, uptime, pending Windows updates, and the battery level of Bluetooth devices and controllers. CPU and GPU temperatures appear when LibreHardwareMonitor is running.
- **Network monitor:** live download and upload speed with a 60-second graph, ping, Wi-Fi name and signal, and your local IP address.
- **Media controls:** see what's playing and control it.
- **App dock:** a row of app icons; one click starts an app. Drop apps on it, drag to reorder, or pick them from a list.
- **Clipboard history:** the last texts you copied; click one to copy it again, or pin it. Copies that password managers mark as secret are never kept, and the history is forgotten when DeskSpace closes unless you choose to keep it.
- **Package tracker:** keeps your tracking numbers until the parcels are delivered. Supports PostNord, GLS, DAO, Bring, DHL, UPS and FedEx. Live status needs a free [17TRACK](https://www.17track.net/) API key; without one, a double-click opens the carrier's tracking page.

### Games

- **Game tiles:** show a fence as cover art instead of icons.
- **Steam and GOG:** add your installed games with one click. Covers are found automatically, and GOG games start through GOG Galaxy when it's installed. GOG shortcuts you drag into a fence are recognised too.
- **Heroic, Epic and Lutris:** games installed through Heroic (GOG, Epic, Amazon), the Epic Games Launcher on Windows and Lutris on Linux appear in Console mode and can be added to a fence.

### Tools

- **Quick search:** press `Ctrl+Shift+Space` to find apps, fence items, desktop items and files. Enter opens the result, Ctrl+Enter shows it in Explorer. The shortcut can be changed.
- **File tidy:** sorts loose downloads into type folders, files older screenshots by month, and finds duplicate downloads. You see a preview first, files are only moved, and the last tidy can be undone. It can run by itself once a day; this is off by default.
- **Disk cleanup:** opens from the System monitor and shows what the Recycle Bin, temporary files, crash reports and old downloads are using. It always asks first.

### Desktop pets

- Up to 8 pets at once: **cat, dog, bear, hamster or rabbit**, in 11 colours, each with its own name.
- They walk along fences, jump between them and nap when you're away. Drag one to pick it up, or click it to make it happy.
- With more than one, they greet each other, play chase, follow each other onto fences and nap side by side. A hamster will ride on a bear.
- Right-click a pet to give it a treat or throw a ball.
- They react to the computer: a CPU that's working hard, a finished download, music starting (with a Media controls widget) and a low battery. This can be switched off in Settings.
- They dress up for Halloween, Christmas, New Year and summer.
- A pet can tell you a minute before a calendar event starts. This needs a calendar link on a clock widget.

### Console mode

A full-screen home screen for a PC on a TV, made to be used from the sofa. Open it from the tray icon or Settings, or set it to start when you sign in.

- **Game library:** your Steam, GOG, Heroic, Epic and Lutris games as a big cover grid, most recently played first.
- **System page:** volume, game launchers, minimize, sleep, restart, shut down and exit to desktop.
- **Game launchers:** open Steam, GOG Galaxy, Epic Games, the EA app, Ubisoft Connect, Battle.net, Amazon Games, Xbox and others you have installed.
- **Pets:** they walk along the bottom of the screen at double size.
- **Controls:** an Xbox-style controller, the keyboard or the mouse. The on-screen hints follow whichever you used last.
- **Playing:** starting a game steps out of the way, and the console comes back when the game ends.
- **Stepping away:** minimizing or closing the console window leaves it running in the background. Hold **Back + Start** on the controller, or use the tray icon, to return to it at any time.

PlayStation controllers aren't read directly yet. They work if a tool such as Steam Input or DS4Windows presents them as an Xbox controller.

## Install

In the project folder:

```bash
bash build/install-linux.sh
```

It asks for your password to install a few system packages, then installs the app for your user in `~/.local/share/deskspace` and starts it. To remove it, run the same script with `--uninstall`. Your data in `~/DeskSpace` is kept.

The Linux version has been tested automatically on Ubuntu with a basic window manager, but not yet by hand on the full Ubuntu or Mint desktops. It differs from the Windows version in a few ways:

- **Fences** stay behind other windows and appear on every workspace. "Show desktop" may hide them on desktops where a file manager draws the icons.
- **Not available:** double-clicking the desktop to hide fences, and hiding the desktop icons. Use the tray icon to hide fences.
- **File previews** cover image files only.
- **Quick search shortcut** is added to the GNOME or Cinnamon keyboard settings, so it also starts DeskSpace when it isn't running. On other desktops, add a shortcut yourself that runs `deskspace --search`.
- **GOG and Epic games** come through [Heroic](https://heroicgameslauncher.com/), since GOG Galaxy doesn't run on Linux.
- **GPU load and VRAM** come from the kernel for AMD cards and from `nvidia-smi` for NVIDIA.
- **File search** needs `locate`, media controls need `playerctl`, and battery levels need `upower`. The install script adds all three.
- **Console mode** reads Xbox-style controllers through the Linux joystick driver.

## Getting started

1. Right-click the DeskSpace tray icon, choose **New**, and pick a fence or widget.
2. Drag icons from your desktop into a fence, or choose **Auto-sort desktop into fences…** from the tray menu.
3. Right-click a fence and choose **Settings…** to change it. Colour, New and Remove are also in the right-click menu.

## Your data

Fences, notes and settings are stored in `~/DeskSpace`, and installing, updating or uninstalling doesn't touch them. To move them to another PC or keep a copy, use **Back up…** in Settings; **Restore…** brings a backup back and saves what you had first. If you're coming from the old DeskFences name, the data folder moves over the first time the app starts.

## Updates

DeskSpace checks GitHub once a day for a new version, and tells you through the tray icon when there is one. Install it from the tray menu, or use **Check now** in Settings. The check sends nothing about you, and you can turn it off in Settings. The update is checked against GitHub's checksum, updates the app's Python libraries without asking for your password, and DeskSpace starts again when it's done. If you installed the `.deb` package instead, the update opens the release page.

## Uninstall

Run `bash build/install-linux.sh --uninstall`. Your `~/DeskSpace` data folder is kept.
