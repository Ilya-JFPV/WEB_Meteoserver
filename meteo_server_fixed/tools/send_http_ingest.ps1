param([string]$HostName="127.0.0.1",[int]$Port=8000,[string]$Code="be3728ec")
$line = "MSR$Code,Sa0,3.2,Da0,180,Ta1,20.1,Hr1,55.0,Pa2,1013.2"
$body = @{ payload = $line } | ConvertTo-Json -Compress
Write-Host ("POST http://{0}:{1}/ingest" -f $HostName,$Port)
Invoke-RestMethod -Uri ("http://{0}:{1}/ingest" -f $HostName,$Port) -Method Post -ContentType "application/json" -Body $body
