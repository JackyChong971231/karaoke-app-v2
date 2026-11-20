# Windows installer and releases

## Release a new version

1. Change `version` in `server/pyproject.toml`, for example to `2.1.0`, and commit.
2. Tag and push:

   ```
   git tag v2.1.0
   git push github build/app
   git push github v2.1.0
   ```

   Push the tag by name. `--follow-tags` skips tags made with a plain `git tag`.

GitHub Actions (`.github/workflows/release.yml`) builds `Karaoke-Setup-2.1.0.exe` and publishes it as a release. It takes about 10 minutes; watch it in the repository's Actions tab. The build fails when the tag does not match `version`.

Installed apps check for the latest release when they start and show an Upgrade button on the control page.

## Files

| File | What it does |
| --- | --- |
| `build.ps1` | Downloads pinned `uv`, `ffmpeg`, and `deno`, stages the app, and runs Inno Setup. Runs locally too, after `npm run build` in `web\`. |
| `karaoke.iss` | The Inno Setup script. Installs per user in `%LOCALAPPDATA%\Programs\Karaoke`, no administrator rights. |
| `Karaoke.cmd` | The installed launcher. Installs Python and the packages on first start (CUDA PyTorch with an NVIDIA card, CPU otherwise), then starts the app. Runs an upgrade when the app exits with code 75. |
| `upgrade.ps1` | Waits for the app to close, runs the new installer silently, and starts the app again. |

## Testing

- `KARAOKE_TORCH=cpu` makes the launcher install the CPU build of PyTorch on a laptop with an NVIDIA card.
- `KARAOKE_UPDATE_URL` points the update check at a stand-in for GitHub's `releases/latest` answer, so an upgrade can be tested without publishing a release.
