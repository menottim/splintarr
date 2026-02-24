#Requires -Version 5.1
<#
.SYNOPSIS
    Generate secure secrets for Vibe-Quality-Searcharr

.DESCRIPTION
    This script generates cryptographically secure random secrets for:
    - Database encryption (DATABASE_KEY)
    - JWT token signing (SECRET_KEY)
    - Password hashing pepper (PEPPER)

.EXAMPLE
    .\generate-secrets.ps1
    Generates all three secret files in the ./secrets directory

.NOTES
    Version: 0.1.0-alpha
    Author: Vibe-Quality-Searcharr
    Requires: PowerShell 5.1+ and .NET Framework 4.5+
#>

[CmdletBinding()]
param()

# Set strict mode
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Color output functions
function Write-Success {
    param([string]$Message)
    Write-Host "✓ $Message" -ForegroundColor Green
}

function Write-ErrorMsg {
    param([string]$Message)
    Write-Host "❌ ERROR: $Message" -ForegroundColor Red
}

function Write-WarningMsg {
    param([string]$Message)
    Write-Host "⚠️  $Message" -ForegroundColor Yellow
}

function Write-InfoMsg {
    param([string]$Message)
    Write-Host "ℹ️  $Message" -ForegroundColor Cyan
}

function Write-Header {
    param([string]$Message)
    Write-Host ""
    Write-Host "================================================================" -ForegroundColor Blue
    Write-Host "  $Message" -ForegroundColor Blue
    Write-Host "================================================================" -ForegroundColor Blue
    Write-Host ""
}

# Generate cryptographically secure random string
function New-SecureSecret {
    param(
        [Parameter(Mandatory=$true)]
        [int]$ByteCount
    )

    try {
        # Use RNGCryptoServiceProvider for cryptographically secure random bytes
        $rng = New-Object System.Security.Cryptography.RNGCryptoServiceProvider
        $bytes = New-Object byte[] $ByteCount
        $rng.GetBytes($bytes)
        $rng.Dispose()

        # Convert to URL-safe base64 (similar to Python's secrets.token_urlsafe)
        $base64 = [Convert]::ToBase64String($bytes)
        $urlSafe = $base64.Replace('+', '-').Replace('/', '_').TrimEnd('=')

        return $urlSafe
    }
    catch {
        Write-ErrorMsg "Failed to generate secure random bytes: $_"
        exit 1
    }
}

# Validate generated secret
function Test-SecretFile {
    param(
        [Parameter(Mandatory=$true)]
        [string]$FilePath,

        [Parameter(Mandatory=$true)]
        [int]$MinLength
    )

    # Check file exists
    if (-not (Test-Path $FilePath)) {
        Write-ErrorMsg "Secret file not created: $FilePath"
        return $false
    }

    # Check file is not empty
    $content = Get-Content $FilePath -Raw -ErrorAction SilentlyContinue
    if ([string]::IsNullOrWhiteSpace($content)) {
        Write-ErrorMsg "Secret file is empty: $FilePath"
        return $false
    }

    $content = $content.Trim()

    # Check minimum length
    if ($content.Length -lt $MinLength) {
        Write-ErrorMsg "Secret too short in $FilePath (expected at least $MinLength chars, got $($content.Length))"
        return $false
    }

    # Check it's not all the same character (basic randomness check)
    $uniqueChars = ($content.ToCharArray() | Select-Object -Unique).Count
    if ($uniqueChars -lt 10) {
        Write-ErrorMsg "Secret appears to be non-random in $FilePath (only $uniqueChars unique characters)"
        return $false
    }

    return $true
}

# Main script execution
try {
    Write-Header "Vibe-Quality-Searcharr Secret Generation"

    # Check PowerShell version
    $psVersion = $PSVersionTable.PSVersion
    Write-InfoMsg "PowerShell Version: $($psVersion.Major).$($psVersion.Minor)"

    if ($psVersion.Major -lt 5) {
        Write-ErrorMsg "PowerShell 5.1 or higher is required. Current version: $psVersion"
        exit 1
    }

    # Check .NET Framework version (required for RNGCryptoServiceProvider)
    try {
        $null = [System.Security.Cryptography.RNGCryptoServiceProvider]
        Write-InfoMsg ".NET Cryptography available"
    }
    catch {
        Write-ErrorMsg ".NET Framework 4.5+ is required but not available"
        exit 1
    }

    # Create secrets directory
    $secretsDir = Join-Path $PSScriptRoot "..\secrets"
    Write-InfoMsg "Creating secrets directory: $secretsDir"

    try {
        if (-not (Test-Path $secretsDir)) {
            $null = New-Item -ItemType Directory -Path $secretsDir -Force
        }
        Write-Success "Secrets directory ready"
    }
    catch {
        Write-ErrorMsg "Failed to create secrets directory: $_"
        exit 1
    }

    Write-Host ""
    Write-Host "Generating cryptographically secure secrets..." -ForegroundColor White
    Write-Host ""

    # Generate database encryption key (32 bytes = 256 bits)
    Write-InfoMsg "Generating database encryption key..."
    try {
        $dbKey = New-SecureSecret -ByteCount 32
        $dbKeyFile = Join-Path $secretsDir "db_key.txt"
        $dbKey | Out-File -FilePath $dbKeyFile -NoNewline -Encoding ASCII -Force

        if (Test-SecretFile -FilePath $dbKeyFile -MinLength 40) {
            Write-Success "Database key generated (32 bytes, 256-bit)"
        }
        else {
            exit 1
        }
    }
    catch {
        Write-ErrorMsg "Failed to generate database key: $_"
        exit 1
    }

    # Generate JWT secret key (64 bytes = 512 bits)
    Write-InfoMsg "Generating JWT secret key..."
    try {
        $secretKey = New-SecureSecret -ByteCount 64
        $secretKeyFile = Join-Path $secretsDir "secret_key.txt"
        $secretKey | Out-File -FilePath $secretKeyFile -NoNewline -Encoding ASCII -Force

        if (Test-SecretFile -FilePath $secretKeyFile -MinLength 80) {
            Write-Success "JWT secret key generated (64 bytes, 512-bit)"
        }
        else {
            exit 1
        }
    }
    catch {
        Write-ErrorMsg "Failed to generate secret key: $_"
        exit 1
    }

    # Generate password hashing pepper (32 bytes = 256 bits)
    Write-InfoMsg "Generating password hashing pepper..."
    try {
        $pepper = New-SecureSecret -ByteCount 32
        $pepperFile = Join-Path $secretsDir "pepper.txt"
        $pepper | Out-File -FilePath $pepperFile -NoNewline -Encoding ASCII -Force

        if (Test-SecretFile -FilePath $pepperFile -MinLength 40) {
            Write-Success "Password pepper generated (32 bytes, 256-bit)"
        }
        else {
            exit 1
        }
    }
    catch {
        Write-ErrorMsg "Failed to generate pepper: $_"
        exit 1
    }

    Write-Host ""
    Write-Host "Setting file permissions..." -ForegroundColor White

    # Set restrictive NTFS permissions (Windows equivalent of chmod 600)
    $secretFiles = Get-ChildItem -Path $secretsDir -Filter "*.txt"
    foreach ($file in $secretFiles) {
        try {
            # Remove inheritance
            $acl = Get-Acl $file.FullName
            $acl.SetAccessRuleProtection($true, $false)

            # Remove all existing rules
            $acl.Access | ForEach-Object { $acl.RemoveAccessRule($_) | Out-Null }

            # Add rule for current user only (Full Control)
            $currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
            $accessRule = New-Object System.Security.AccessControl.FileSystemAccessRule(
                $currentUser,
                "FullControl",
                "Allow"
            )
            $acl.AddAccessRule($accessRule)

            Set-Acl -Path $file.FullName -AclObject $acl
            Write-Success "Permissions set on $($file.Name) (current user only)"
        }
        catch {
            Write-WarningMsg "Could not set permissions on $($file.Name): $_"
        }
    }

    Write-Host ""
    Write-Host "Verifying generated secrets..." -ForegroundColor White

    # Final verification
    $allValid = $true
    $secretFileNames = @("db_key.txt", "secret_key.txt", "pepper.txt")

    foreach ($fileName in $secretFileNames) {
        $filePath = Join-Path $secretsDir $fileName
        if (Test-Path $filePath) {
            $fileSize = (Get-Item $filePath).Length
            Write-Success "$fileName verified ($fileSize bytes)"
        }
        else {
            Write-ErrorMsg "$fileName verification failed"
            $allValid = $false
        }
    }

    if ($allValid) {
        Write-Host ""
        Write-Host "================================================================" -ForegroundColor Green
        Write-Host "✅ SUCCESS: All secrets generated and verified!" -ForegroundColor Green
        Write-Host "================================================================" -ForegroundColor Green
        Write-Host ""
        Write-Host "Generated files in $secretsDir:" -ForegroundColor White
        Write-Host "  - db_key.txt      (Database encryption key)" -ForegroundColor Gray
        Write-Host "  - secret_key.txt  (JWT signing key)" -ForegroundColor Gray
        Write-Host "  - pepper.txt      (Password hashing pepper)" -ForegroundColor Gray
        Write-Host ""
        Write-Host "⚠️  CRITICAL SECURITY WARNINGS:" -ForegroundColor Yellow
        Write-Host ""
        Write-Host "  1. NEVER commit these files to version control" -ForegroundColor White
        Write-Host "  2. BACKUP these files securely (encrypted backup)" -ForegroundColor White
        Write-Host "  3. If you lose these files, you CANNOT decrypt your database" -ForegroundColor White
        Write-Host "  4. Store backups in multiple secure locations:" -ForegroundColor White
        Write-Host "     - Password manager (1Password, Bitwarden, etc.)" -ForegroundColor Gray
        Write-Host "     - Encrypted USB drive" -ForegroundColor Gray
        Write-Host "     - Secure cloud storage (encrypted)" -ForegroundColor Gray
        Write-Host ""
        Write-Host "ℹ️  Next Steps:" -ForegroundColor Cyan
        Write-Host ""
        Write-Host "  1. Start the application:" -ForegroundColor White
        Write-Host "     docker-compose up -d" -ForegroundColor Gray
        Write-Host ""
        Write-Host "  2. Access the setup wizard:" -ForegroundColor White
        Write-Host "     http://localhost:7337" -ForegroundColor Gray
        Write-Host ""
        Write-Host "  3. See Windows deployment guide:" -ForegroundColor White
        Write-Host "     docs/how-to-guides/windows-quick-start.md" -ForegroundColor Gray
        Write-Host ""

        exit 0
    }
    else {
        Write-ErrorMsg "Secret validation failed. Please review errors above."
        exit 1
    }
}
catch {
    Write-ErrorMsg "Unexpected error: $_"
    Write-Host $_.ScriptStackTrace -ForegroundColor Red
    exit 1
}
