# docs/dung-ban-in.ps1 — dựng lại bản HTML và PDF từ file .md nguồn.
#
#     powershell -NoProfile -ExecutionPolicy Bypass -File docs/dung-ban-in.ps1
#
# Chạy từ thư mục gốc repo. Cần pandoc và Microsoft Edge (hoặc Chrome).
#
# VÌ SAO CÓ SCRIPT NÀY
# --------------------
# File .md là nguồn sự thật; .html và .pdf là bản dẫn xuất. Sửa .md rồi quên
# dựng lại thì bản PDF người ta cầm đi họp nói một đằng, repo nói một nẻo —
# đúng kiểu lệch mà AGENTS.md R4 sinh ra để chặn. Chạy script này trong cùng
# PR với mọi lần sửa hai file .md dưới đây.
#
# Hình vẽ nằm ở docs/hinh/*.svg, viết tay, KHÔNG sinh tự động. Sửa sơ đồ thì
# sửa thẳng file .svg.

# KHONG dat ErrorActionPreference = "Stop" o pham vi script, va KHONG dung
# `2>&1` tren lenh native. Windows PowerShell 5.1 boc moi dong stderr cua mot
# .exe thanh ErrorRecord, nen Edge in mot canh bao vo hai ve renderer la ca
# script dung lai du PDF da tao xong. Script tu kiem ket qua bang Test-Path.
$ErrorActionPreference = "Continue"

$TaiLieu = @{
    "SO_TAY_NGUOI_MOI" = "ANSER Brain - So tay cho nguoi moi"
    "GIAO_VIEC_BRAIN"  = "ANSER Brain - Ho so ban giao"
    "SRS_CHU_KY_01"    = "ANSER - SRS chu ky 01"
}

function Tim-Lenh([string[]]$duongDan, [string]$ten) {
    foreach ($p in $duongDan) { if (Test-Path $p) { return $p } }
    $c = Get-Command $ten -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    throw "Khong tim thay $ten. Cai dat roi chay lai."
}

$pandoc = Tim-Lenh @(
    "$env:LOCALAPPDATA\Pandoc\pandoc.exe",
    "C:\Program Files\Pandoc\pandoc.exe"
) "pandoc"

$trinhDuyet = Tim-Lenh @(
    "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "C:\Program Files\Google\Chrome\Application\chrome.exe",
    "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
) "msedge"

$goc = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $goc
New-Item -ItemType Directory -Force -Path "docs\ban-in" | Out-Null

foreach ($ten in $TaiLieu.Keys) {
    $md = Join-Path $goc "$ten.md"
    if (-not (Test-Path $md)) { Write-Warning "Bo qua: khong thay $ten.md"; continue }

    $html = Join-Path $goc "docs\ban-in\$ten.html"
    $pdf  = Join-Path $goc "docs\ban-in\$ten.pdf"

    # --embed-resources nhung SVG thang vao HTML -> file tu chay duoc, gui di duoc.
    & $pandoc $md -f gfm -t html5 --standalone --embed-resources `
        --toc --toc-depth=3 -V pagetitle="$($TaiLieu[$ten])" `
        --css docs/in-pdf.css -o $html

    if (Test-Path $pdf) { Remove-Item $pdf -Force }
    $url = "file:///" + ($html -replace '\\', '/')
    & $trinhDuyet --headless --disable-gpu --no-pdf-header-footer `
        --print-to-pdf="$pdf" $url 2>$null

    # Edge ghi file xong SAU khi tien trinh tra quyen dieu khien, nen mot
    # Start-Sleep co dinh lam script bao "khong tao ra" trong khi PDF da nam
    # day. Cho tung buoc den khi kich thuoc file thoi tang.
    $truoc = -1
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Milliseconds 500
        if (-not (Test-Path $pdf)) { continue }
        $nay = (Get-Item $pdf).Length
        if ($nay -gt 0 -and $nay -eq $truoc) { break }
        $truoc = $nay
    }

    if (Test-Path $pdf) {
        $kb = [math]::Round((Get-Item $pdf).Length / 1KB)
        Write-Host "OK  $ten.html + $ten.pdf ($kb KB)"
    } else {
        Write-Warning "$ten.pdf khong duoc tao ra"
    }
}

Write-Host ""
Write-Host "Ban in nam o: docs\ban-in\"
