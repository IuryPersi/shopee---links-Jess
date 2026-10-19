<#
  Agenda o robo para atualizar os achados 3 vezes por dia, SEM abrir janela.
  So instale DEPOIS que o "Testar conexao com a Shopee" der TUDO CERTO.

  Instalar:  powershell -NoProfile -ExecutionPolicy Bypass -File "W:\Robo Shopee\agendar.ps1"
  Remover:   powershell -NoProfile -ExecutionPolicy Bypass -File "W:\Robo Shopee\agendar.ps1" -Remover
  Outros horarios: ... agendar.ps1 -Horarios 07:30,12:30,20:00

  Usa conhost.exe --headless: nesta maquina uma tarefa com console comum abre uma janela do
  Windows Terminal, e fecha-la mata a atualizacao no meio.
  So mexe nas tarefas que ELE criou: nome "Robo Shopee - achados HHhMM" E a marca no comeco da descricao.
  Valida tudo antes de mexer; se o registro falhar no meio, devolve as tarefas antigas como estavam.
  Testado em tests/test_agendar.py com as tarefas do Windows simuladas.
#>
param(
    [switch]$Remover,
    [string[]]$Horarios = @("08:00", "13:00", "19:00")
)
$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $MyInvocation.MyCommand.Path
$marca = "[robo-shopee-agendar.ps1]"
$padraoNome = '^Robo Shopee - achados \d{2}h\d{2}$'

function Test-TarefaDoRobo($t) {
    # comparacao LITERAL: com -like os colchetes da marca viram curinga invalido (34a rodada do Codex)
    ($t.TaskName -match $padraoNome) -and ($null -ne $t.Description) -and
        ([string]$t.Description).StartsWith($marca, [System.StringComparison]::Ordinal)
}

$todas = @(Get-ScheduledTask -ErrorAction SilentlyContinue)
$doRobo = @($todas | Where-Object { Test-TarefaDoRobo $_ })

if ($Remover) {
    foreach ($t in $doRobo) {
        Unregister-ScheduledTask -TaskName $t.TaskName -TaskPath $t.TaskPath -Confirm:$false
        "removida: $($t.TaskName)"
    }
    if ($doRobo.Count -eq 0) { "Nenhuma tarefa do robo para remover." }
    return
}

# 1) valida TUDO antes de mexer em qualquer tarefa
# com -File o PowerShell entrega "07:30,12:30" como UM texto so: separa nas virgulas
$Horarios = @($Horarios | ForEach-Object { $_ -split ',' } | ForEach-Object { $_.Trim() } |
    Where-Object { $_ } | Sort-Object -Unique)
if ($Horarios.Count -eq 0) { throw "Nenhum horario informado (ex.: -Horarios 08:00,13:00,19:00)" }
foreach ($h in $Horarios) {
    if ($h -notmatch '^(?:[01]\d|2[0-3]):[0-5]\d$') { throw "Horario invalido: '$h' (use HH:MM, ex.: 08:00)" }
}
$nomes = @($Horarios | ForEach-Object { "Robo Shopee - achados $($_.Replace(':', 'h'))" })
foreach ($nome in $nomes) {
    $alheia = @($todas | Where-Object { $_.TaskName -eq $nome -and $_.TaskPath -eq '\' -and -not (Test-TarefaDoRobo $_) })
    if ($alheia.Count -gt 0) {
        throw "Ja existe uma tarefa '$nome' que NAO foi criada por este script. Renomeie-a ou use outro horario."
    }
}
try { $python = "$(& py -3.12 -c 'import sys; print(sys.executable)')".Trim() } catch { $python = "" }
if (-not $python -or -not (Test-Path -LiteralPath $python)) { throw "Python 3.12 nao encontrado (py -3.12)." }
if (-not (Test-Path -LiteralPath (Join-Path $raiz "robo\__main__.py"))) { throw "Pasta do robo nao encontrada: $raiz" }

# 2) monta tudo antes (erro aqui ainda nao mexeu em nada)
$acoes = @(); $gatilhos = @()
foreach ($h in $Horarios) {
    $acoes += New-ScheduledTaskAction -Execute "conhost.exe" -Argument "--headless `"$python`" -m robo rodar" `
        -WorkingDirectory $raiz
    $gatilhos += New-ScheduledTaskTrigger -Daily -At $h
}
$ajustes = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -MultipleInstances IgnoreNew
$copias = @(foreach ($t in $doRobo) {
    [pscustomobject]@{ TaskName = $t.TaskName; TaskPath = $t.TaskPath
                       Xml = (Export-ScheduledTask -TaskName $t.TaskName -TaskPath $t.TaskPath) }
})

# 3) troca so as tarefas do robo, com VOLTA ATRAS (35a rodada do Codex): se falhar no meio, remove
#    as novas desta vez e devolve as antigas exatamente como estavam (copia XML de antes)
$criadas = New-Object System.Collections.Generic.List[string]
try {
    foreach ($t in $doRobo) {
        Unregister-ScheduledTask -TaskName $t.TaskName -TaskPath $t.TaskPath -Confirm:$false
    }
    for ($i = 0; $i -lt $Horarios.Count; $i++) {
        Register-ScheduledTask -TaskName $nomes[$i] -Action $acoes[$i] -Trigger $gatilhos[$i] -Settings $ajustes `
            -Description "$marca Atualiza os achadinhos da Shopee ($raiz). Log: saida\robo.log" | Out-Null
        $criadas.Add($nomes[$i])
    }
} catch {
    $falha = $_.Exception.Message
    # cada passo da volta atras e conferido: "nada mudou" so quando TUDO voltou (36a rodada)
    $naoSaiu = @()
    foreach ($n in $criadas) {
        try { Unregister-ScheduledTask -TaskName $n -TaskPath '\' -Confirm:$false } catch { $naoSaiu += $n }
    }
    $naoVoltou = @()
    foreach ($c in $copias) {
        try { Register-ScheduledTask -Xml $c.Xml -TaskName $c.TaskName -TaskPath $c.TaskPath -Force | Out-Null }
        catch { $naoVoltou += $c.TaskName }
    }
    if ($naoSaiu.Count -gt 0 -or $naoVoltou.Count -gt 0) {
        $partes = @()
        if ($naoSaiu.Count -gt 0) { $partes += "continuam agendadas e NAO consegui remover: $($naoSaiu -join ', ')" }
        if ($naoVoltou.Count -gt 0) { $partes += "NAO consegui devolver: $($naoVoltou -join ', ')" }
        throw ("Falhou no meio ($falha). ATENCAO: $($partes -join '; '). Confira no Agendador de Tarefas " +
            "e rode o script de novo (ou com -Remover).")
    }
    throw "Falhou no meio ($falha). Voltei as tarefas do robo como estavam; nada mudou."
}
foreach ($t in $doRobo) { "substituida: $($t.TaskName)" }
foreach ($n in $nomes) { "agendada: $n" }
"Pronto. O resultado de cada atualizacao fica em $raiz\saida\robo.log e na tela Achadinhos de hoje."
