param(
  [string]$OutDir = (Join-Path $PSScriptRoot "..\\static\\img\\brands"),
  [switch]$Force
)

$ErrorActionPreference = "Stop"

New-Item -ItemType Directory -Path $OutDir -Force | Out-Null

$items = @(
  @{
    Name = "Blockly"
    Url  = "https://cdn.simpleicons.org/blockly/F7C948"
    File = "blockly.svg"
  },
  @{
    Name = "Scratch"
    Url  = "https://cdn.simpleicons.org/scratch/FF8C1A"
    File = "scratch.svg"
  },
  @{
    Name = "Python"
    Url  = "https://cdn.simpleicons.org/python/3776AB"
    File = "python.svg"
  }
)

foreach ($item in $items) {
  $dest = Join-Path $OutDir $item.File
  if ((Test-Path $dest) -and (-not $Force)) {
    Write-Host "Skipping $($item.Name) (already exists). Use -Force to overwrite."
    continue
  }

  Write-Host "Downloading $($item.Name) from $($item.Url)"
  Invoke-WebRequest -Uri $item.Url -OutFile $dest -UseBasicParsing

  $head = (Get-Content $dest -TotalCount 2 -ErrorAction SilentlyContinue) -join "`n"
  if ($head -notmatch "<svg") {
    throw "Downloaded file for $($item.Name) does not look like SVG: $dest"
  }
}

Write-Host "Done. Logos saved to: $OutDir"
