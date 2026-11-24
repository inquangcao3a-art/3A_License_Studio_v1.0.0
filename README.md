name: Studio Windows - Package and verify

on:
  workflow_dispatch:

jobs:
  build-studio:
    runs-on: windows-latest
    timeout-minutes: 25

    steps:
      - name: Checkout source
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install build dependencies
        shell: pwsh
        run: |
          python -m pip install -r requirements.txt 'pyinstaller>=6.16,<7'
          if ($LASTEXITCODE -ne 0) { throw 'Dependency install failed' }

      - name: Install Inno Setup
        shell: pwsh
        run: |
          $compiler = Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'
          if (!(Test-Path -LiteralPath $compiler)) {
            choco install innosetup --yes --no-progress
            if ($LASTEXITCODE -ne 0) { throw 'Inno Setup install failed' }
          }

      - name: Build Studio EXE and installer together
        shell: pwsh
        run: .\build-windows.ps1

      - name: Upload Studio installer
        uses: actions/upload-artifact@v4
        with:
          name: 3A_License_Studio_1.0.3_Setup_Windows
          path: output/3A_License_Studio_1.0.3_Setup.exe
          if-no-files-found: error
