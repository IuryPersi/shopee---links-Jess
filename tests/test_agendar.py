"""agendar.ps1 rodando de verdade no PowerShell, com as tarefas do Windows SIMULADAS.

Get/Register/Unregister-ScheduledTask viram funcoes falsas (funcao tem precedencia sobre o comando
do Windows). O roteiro ABORTA antes de chamar o agendar.ps1 se a troca nao pegou, e confere no fim
que o numero de tarefas reais 'Robo Shopee*' nao mudou: nada e criado nem apagado no Windows.
"""
from __future__ import annotations

import base64
import shutil
import subprocess
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SCRIPT = RAIZ / "agendar.ps1"
POWERSHELL = shutil.which("powershell")
MARCA = "[robo-shopee-agendar.ps1]"

ROBO_08 = f"[pscustomobject]@{{TaskName='Robo Shopee - achados 08h00'; TaskPath='\\'; Description='{MARCA} Atualiza'}}"
ROBO_19 = f"[pscustomobject]@{{TaskName='Robo Shopee - achados 19h00'; TaskPath='\\'; Description='{MARCA} Atualiza'}}"
ALHEIA_13 = "[pscustomobject]@{TaskName='Robo Shopee - achados 13h00'; TaskPath='\\'; Description='de outra pessoa'}"
SEM_DESCRICAO_19 = "[pscustomobject]@{TaskName='Robo Shopee - achados 19h00'; TaskPath='\\'; Description=$null}"
OUTRO_NOME = f"[pscustomobject]@{{TaskName='Backup diario'; TaskPath='\\'; Description='{MARCA} outro nome'}}"

TRES = "-Horarios '08:00,13:00,19:00'"
# nome: argumentos, tarefas que "existem" e as falhas simuladas: falhar = n-esimo registro novo que
# falha (0 = nenhum), devolucao = a devolucao das antigas falha, remocao = nome cuja remocao falha
CENARIOS = {
    # a marca so e avaliada quando o NOME bate: era ai que o -like quebrava (34a rodada)
    "remover": {"args": "-Remover", "tarefas": [ROBO_08, ALHEIA_13, SEM_DESCRICAO_19, OUTRO_NOME]},
    "remover_vazio": {"args": "-Remover", "tarefas": []},
    # com -File o PowerShell entrega "13:00,08:00,13:00" como UM texto
    "instalar_virgula": {"args": "-Horarios '13:00,08:00,13:00'", "tarefas": [ROBO_08]},
    "colisao": {"args": "-Horarios '08:00,13:00'", "tarefas": [ROBO_08, ALHEIA_13]},
    "horario_invalido": {"args": "-Horarios '08:00,25:00'", "tarefas": [ROBO_08]},
    # 35a rodada: o 2o registro falha -> volta atras
    "falha_no_meio": {"args": TRES, "tarefas": [ROBO_08, ROBO_19], "falhar": 2},
    "falha_sem_volta": {"args": TRES, "tarefas": [ROBO_08, ROBO_19], "falhar": 2, "devolucao": True},
    # 36a rodada: a remocao compensatoria da nova 08h00 tambem falha
    "falha_na_remocao": {"args": TRES, "tarefas": [ROBO_19], "falhar": 2,
                         "remocao": "Robo Shopee - achados 08h00"},
}

MOLDE = r"""
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$ErrorActionPreference = 'Stop'
Import-Module ScheduledTasks
$reaisAntes = @(ScheduledTasks\Get-ScheduledTask -ErrorAction SilentlyContinue |
    Where-Object { $_.TaskName -like 'Robo Shopee*' }).Count
$global:chamadas = New-Object System.Collections.Generic.List[string]
$global:tarefas = @()
$global:falharNoRegistro = 0; $global:registros = 0; $global:falharDevolucao = $false; $global:falharRemocao = ''
function global:Get-ScheduledTask { [CmdletBinding()] param() $global:tarefas }
function global:Export-ScheduledTask { [CmdletBinding()] param($TaskName, $TaskPath)
    $global:chamadas.Add("export|$TaskPath$TaskName"); "<xml de $TaskName>" }
function global:Unregister-ScheduledTask { [CmdletBinding(SupportsShouldProcess = $true)] param($TaskName, $TaskPath)
    if ($TaskName -eq $global:falharRemocao) { $global:chamadas.Add("remocao-falhou|$TaskPath$TaskName"); throw 'falha simulada na remocao' }
    $global:chamadas.Add("unregister|$TaskPath$TaskName") }
function global:Register-ScheduledTask { [CmdletBinding()]
    param($TaskName, $Action, $Trigger, $Settings, $Description, $Xml, $TaskPath, [switch]$Force)
    if ($Xml) {
        if ($global:falharDevolucao) { $global:chamadas.Add("devolucao-falhou|$TaskPath$TaskName"); throw 'falha simulada na devolucao' }
        $global:chamadas.Add("devolvida|$TaskPath$TaskName|$Xml|force=$Force"); return 'devolvida'
    }
    $global:registros++
    if ($global:registros -eq $global:falharNoRegistro) { $global:chamadas.Add("falhou|$TaskName"); throw 'falha simulada no registro' }
    $global:chamadas.Add("register|$TaskName|$($Action.Execute)|$($Action.Arguments)|$($Action.WorkingDirectory)|$Description")
    'registrada' }
$null = New-ScheduledTaskAction -Execute 'x.exe'
foreach ($c in 'Get-ScheduledTask', 'Export-ScheduledTask', 'Register-ScheduledTask', 'Unregister-ScheduledTask') {
    if ((Get-Command $c).Definition -notmatch 'global:(chamadas|tarefas)') { throw "SIMULACAO NAO ATIVA: $c" }
}
%CENARIOS%
$reaisDepois = @(ScheduledTasks\Get-ScheduledTask -ErrorAction SilentlyContinue |
    Where-Object { $_.TaskName -like 'Robo Shopee*' }).Count
"REAIS|$reaisAntes|$reaisDepois"
"""

UM_CENARIO = r"""
$global:tarefas = @(%TAREFAS%); $global:chamadas.Clear()
$global:falharNoRegistro = %FALHAR%; $global:registros = 0; $global:falharDevolucao = %DEVOLUCAO%
$global:falharRemocao = '%REMOCAO%'
"CENARIO|%NOME%"
try { & '%SCRIPT%' %ARGS% | ForEach-Object { "SAIDA|$_" } } catch { "ERRO|$($_.Exception.Message)" }
$global:chamadas | ForEach-Object { "CHAMADA|$_" }
"""


@unittest.skipUnless(POWERSHELL and shutil.which("py"), "precisa do Windows PowerShell e do py")
class TestAgendar(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        partes = [UM_CENARIO.replace("%TAREFAS%", ", ".join(c["tarefas"])).replace("%NOME%", nome)
                  .replace("%SCRIPT%", str(SCRIPT)).replace("%ARGS%", c["args"])
                  .replace("%FALHAR%", str(c.get("falhar", 0)))
                  .replace("%DEVOLUCAO%", "$true" if c.get("devolucao") else "$false")
                  .replace("%REMOCAO%", c.get("remocao", ""))
                  for nome, c in CENARIOS.items()]
        roteiro = MOLDE.replace("%CENARIOS%", "\n".join(partes))
        codificado = base64.b64encode(roteiro.encode("utf-16-le")).decode("ascii")
        r = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                            "-EncodedCommand", codificado], capture_output=True, timeout=180)
        saida = r.stdout.decode("utf-8", "replace")
        cls.reais = None
        cls.res: dict[str, dict] = {}
        atual = None
        for linha in saida.splitlines():
            tipo, _, resto = linha.partition("|")
            if tipo == "CENARIO":
                atual = cls.res.setdefault(resto, {"saida": [], "erro": None, "chamadas": []})
            elif tipo == "SAIDA" and atual is not None:
                atual["saida"].append(resto)
            elif tipo == "ERRO" and atual is not None:
                atual["erro"] = resto
            elif tipo == "CHAMADA" and atual is not None:
                atual["chamadas"].append(resto)
            elif tipo == "REAIS":
                cls.reais = resto.split("|")
        if set(cls.res) != set(CENARIOS):
            raise AssertionError(f"roteiro nao completou (codigo {r.returncode}):\n{saida}\n"
                                 f"{r.stderr.decode('utf-8', 'replace')}")

    def test_nenhuma_tarefa_real_mudou(self):
        self.assertIsNotNone(self.reais)
        self.assertEqual(self.reais[0], self.reais[1])

    def test_remover_so_as_tarefas_do_robo_sem_quebrar_na_marca(self):
        r = self.res["remover"]
        self.assertIsNone(r["erro"], r["erro"])
        self.assertEqual(r["chamadas"], ["unregister|\\Robo Shopee - achados 08h00"])
        self.assertIn("removida: Robo Shopee - achados 08h00", r["saida"])

    def test_remover_sem_nada_para_remover(self):
        r = self.res["remover_vazio"]
        self.assertIsNone(r["erro"], r["erro"])
        self.assertEqual(r["chamadas"], [])
        self.assertIn("Nenhuma tarefa do robo para remover.", r["saida"])

    def test_instalar_com_horarios_separados_por_virgula(self):
        r = self.res["instalar_virgula"]
        self.assertIsNone(r["erro"], r["erro"])
        self.assertEqual(r["chamadas"][:2], ["export|\\Robo Shopee - achados 08h00",  # copia antes de mexer
                                             "unregister|\\Robo Shopee - achados 08h00"])
        registros = [c.split("|") for c in r["chamadas"][2:]]
        self.assertEqual([x[1] for x in registros], ["Robo Shopee - achados 08h00", "Robo Shopee - achados 13h00"])
        for _, _, executa, argumentos, pasta, descricao in registros:
            self.assertEqual(executa, "conhost.exe")
            self.assertTrue(argumentos.startswith("--headless \""), argumentos)
            self.assertTrue(argumentos.endswith("\" -m robo rodar"), argumentos)
            self.assertEqual(Path(pasta), RAIZ)
            self.assertTrue(descricao.startswith(MARCA), descricao)

    def test_tarefa_alheia_com_o_mesmo_nome_para_antes_de_mexer(self):
        r = self.res["colisao"]
        self.assertIn("NAO foi criada por este script", r["erro"] or "")
        self.assertEqual(r["chamadas"], [])  # nem a tarefa do robo foi removida

    def test_horario_invalido_para_antes_de_mexer(self):
        r = self.res["horario_invalido"]
        self.assertIn("Horario invalido: '25:00'", r["erro"] or "")
        self.assertEqual(r["chamadas"], [])

    def test_falha_no_meio_volta_tudo_como_estava(self):
        r = self.res["falha_no_meio"]
        self.assertEqual(r["chamadas"][:4], [
            "export|\\Robo Shopee - achados 08h00", "export|\\Robo Shopee - achados 19h00",
            "unregister|\\Robo Shopee - achados 08h00", "unregister|\\Robo Shopee - achados 19h00"])
        self.assertTrue(r["chamadas"][4].startswith("register|Robo Shopee - achados 08h00|"), r["chamadas"])
        self.assertEqual(r["chamadas"][5:], [
            "falhou|Robo Shopee - achados 13h00",
            "unregister|\\Robo Shopee - achados 08h00",  # a nova desta vez sai
            "devolvida|\\Robo Shopee - achados 08h00|<xml de Robo Shopee - achados 08h00>|force=True",
            "devolvida|\\Robo Shopee - achados 19h00|<xml de Robo Shopee - achados 19h00>|force=True"])
        self.assertIn("Voltei as tarefas do robo como estavam; nada mudou.", r["erro"] or "")
        self.assertIn("falha simulada no registro", r["erro"] or "")
        self.assertEqual(r["saida"], [])  # nada de "agendada:" quando falhou

    def test_falha_sem_conseguir_devolver_avisa_quais(self):
        r = self.res["falha_sem_volta"]
        self.assertIn("NAO consegui devolver: Robo Shopee - achados 08h00, Robo Shopee - achados 19h00",
                      r["erro"] or "")
        self.assertNotIn("nada mudou", r["erro"] or "")

    def test_remocao_compensatoria_que_falha_nao_vira_nada_mudou(self):
        r = self.res["falha_na_remocao"]
        erro = r["erro"] or ""
        self.assertIn("continuam agendadas e NAO consegui remover: Robo Shopee - achados 08h00", erro)
        self.assertNotIn("nada mudou", erro)
        self.assertIn("remocao-falhou|\\Robo Shopee - achados 08h00", r["chamadas"])
        self.assertIn("devolvida|\\Robo Shopee - achados 19h00|<xml de Robo Shopee - achados 19h00>|force=True",
                      r["chamadas"])  # a antiga voltou mesmo assim


if __name__ == "__main__":
    unittest.main()
