$ErrorActionPreference = 'Stop'

Add-Type -AssemblyName System.Drawing

function New-Icon {
    param(
        [Parameter(Mandatory = $true)][int]$Size,
        [Parameter(Mandatory = $true)][string]$Path
    )

    $bitmap = New-Object System.Drawing.Bitmap($Size, $Size, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    try {
        $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
        $scale = $Size / 96.0
        $graphics.Clear([System.Drawing.Color]::FromArgb(17, 24, 39))

        $bubbleBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(245, 158, 11))
        $darkPen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(17, 24, 39), [float](6 * $scale))
        $greenBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(34, 197, 94))
        $greenPen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(5, 46, 22), [float](3 * $scale))
        try {
            $x = [float](15 * $scale)
            $y = [float](31 * $scale)
            $width = [float](66 * $scale)
            $height = [float](38 * $scale)
            $radius = [float](8 * $scale)
            $graphics.FillRectangle($bubbleBrush, $x + $radius, $y, $width - (2 * $radius), $height)
            $graphics.FillRectangle($bubbleBrush, $x, $y + $radius, $width, $height - (2 * $radius))
            $graphics.FillEllipse($bubbleBrush, $x, $y, 2 * $radius, 2 * $radius)
            $graphics.FillEllipse($bubbleBrush, $x + $width - (2 * $radius), $y, 2 * $radius, 2 * $radius)
            $graphics.FillEllipse($bubbleBrush, $x, $y + $height - (2 * $radius), 2 * $radius, 2 * $radius)
            $graphics.FillEllipse($bubbleBrush, $x + $width - (2 * $radius), $y + $height - (2 * $radius), 2 * $radius, 2 * $radius)
            $graphics.FillRectangle($bubbleBrush, [float](28 * $scale), [float](63 * $scale), [float](7 * $scale), [float](16 * $scale))
            $graphics.DrawLine($darkPen, [float](32 * $scale), [float](45 * $scale), [float](64 * $scale), [float](45 * $scale))
            $graphics.DrawLine($darkPen, [float](32 * $scale), [float](56 * $scale), [float](52 * $scale), [float](56 * $scale))
            $graphics.FillEllipse($greenBrush, [float](60 * $scale), [float](12 * $scale), [float](20 * $scale), [float](20 * $scale))
            $graphics.DrawLine($greenPen, [float](65 * $scale), [float](22 * $scale), [float](68 * $scale), [float](25 * $scale))
            $graphics.DrawLine($greenPen, [float](68 * $scale), [float](25 * $scale), [float](74 * $scale), [float](18 * $scale))
        }
        finally {
            $bubbleBrush.Dispose()
            $darkPen.Dispose()
            $greenBrush.Dispose()
            $greenPen.Dispose()
        }
        $bitmap.Save($Path, [System.Drawing.Imaging.ImageFormat]::Png)
    }
    finally {
        $graphics.Dispose()
        $bitmap.Dispose()
    }
}

$IconRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\icons')).Path
New-Icon -Size 48 -Path (Join-Path $IconRoot 'icon-48.png')
New-Icon -Size 96 -Path (Join-Path $IconRoot 'icon-96.png')
