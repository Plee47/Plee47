"""Gera as imagens do perfil em assets/, nos temas claro e escuro.

Os fatos ficam em dados/perfil.json. Da API pública do GitHub vêm a contagem de
repositórios, a data da última atividade, as linguagens e o status do CI. Sem
mudança nos dados, os arquivos saem idênticos e o robô não cria commit.

O texto vira curva vetorial, então o SVG fica igual em qualquer sistema.

Uso:
    pip install -r scripts/requirements.txt
    python scripts/gerar_svgs.py
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path

import uharfbuzz as hb
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

RAIZ = Path(__file__).resolve().parent.parent
LARGURA = 960
X_CELULA = 96
X_FIM = LARGURA - 24

TEMAS = {
    "escuro": {
        "fundo": "#10151C",
        "barra": "#171D26",
        "celula": "#171D26",
        "borda": "#2C3540",
        "texto": "#E8EEF4",
        "suave": "#A0ACB9",
        "destaque": "#F58A4B",
        "entrada": "#7FB8F5",
        "texto_codigo": "#8FDCAB",
        "ok": "#58C58A",
        "erro": "#F47C7C",
        "listra": "#151B23",
    },
    "claro": {
        "fundo": "#FFFFFF",
        "barra": "#F4F6F8",
        "celula": "#F4F6F8",
        "borda": "#D5DBE1",
        "texto": "#1C232B",
        "suave": "#56616D",
        "destaque": "#B9490A",
        "entrada": "#0B5CAD",
        "texto_codigo": "#116A38",
        "ok": "#1A7F45",
        "erro": "#C22F2F",
        "listra": "#F9FAFB",
    },
}


class Fonte:
    def __init__(self, caminho: Path):
        self.tt = TTFont(caminho)
        self.glifos = self.tt.getGlyphSet()
        self.ordem = self.tt.getGlyphOrder()
        self.upem = self.tt["head"].unitsPerEm
        self.hb = hb.Font(hb.Face(hb.Blob.from_file_path(str(caminho))))

    def _moldar(self, conteudo: str):
        buf = hb.Buffer()
        buf.add_str(conteudo)
        buf.guess_segment_properties()
        # Sem ligaturas: "!=" e "->" devem aparecer como foram escritos.
        hb.shape(self.hb, buf, {"kern": True, "liga": False, "calt": False})
        return buf.glyph_infos, buf.glyph_positions

    def largura(self, conteudo: str, tam: float) -> float:
        _, pos = self._moldar(conteudo)
        return sum(p.x_advance for p in pos) * tam / self.upem

    def caminho(self, conteudo: str, x: float, y: float, tam: float) -> str:
        infos, pos = self._moldar(conteudo)
        esc = tam / self.upem
        pen = SVGPathPen(self.glifos, ntos=lambda v: f"{v:.1f}".rstrip("0").rstrip("."))
        cx = x
        for info, p in zip(infos, pos):
            self.glifos[self.ordem[info.codepoint]].draw(
                TransformPen(pen, (esc, 0, 0, -esc, cx + p.x_offset * esc, y - p.y_offset * esc))
            )
            cx += p.x_advance * esc
        return pen.getCommands()


class Tela:
    """Acumula as partes de um SVG e oferece os elementos do notebook."""

    def __init__(self, fontes: dict, cores: dict, altura: int, titulo: str, css: str = ""):
        self.f, self.c, self.altura = fontes, cores, altura
        titulo = titulo.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")
        self.partes = [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {LARGURA} {altura}" '
            f'width="{LARGURA}" height="{altura}" role="img" aria-label="{titulo}">'
            f"<title>{titulo}</title>{css}"
            f'<rect x=".5" y=".5" width="{LARGURA - 1}" height="{altura - 1}" rx="10" '
            f'fill="{cores["fundo"]}" stroke="{cores["borda"]}"/>'
        ]

    def add(self, s: str) -> None:
        self.partes.append(s)

    def texto(self, fonte: str, conteudo: str, x: float, y: float, tam: float, cor: str, ancora: str = "i") -> float:
        f = self.f[fonte]
        larg = f.largura(conteudo, tam)
        if ancora == "f":
            x -= larg
        elif ancora == "m":
            x -= larg / 2
        self.add(f'<path fill="{self.c[cor]}" d="{f.caminho(conteudo, x, y, tam)}"/>')
        return x + larg

    def codigo(self, tokens: list, x: float, y: float) -> None:
        for conteudo, cor in tokens:
            x = self.texto("mono", conteudo, x, y, 15.5, cor)

    def entrada(self, n: int, tokens: list, y: float) -> float:
        """Desenha uma célula de código e devolve o y logo abaixo dela."""
        c = self.c
        self.texto("mono", f"In [{n}]:", X_CELULA - 12, y + 25, 13.5, "entrada", "f")
        self.add(
            f'<rect x="{X_CELULA}" y="{y}" width="{X_FIM - X_CELULA}" height="38" rx="5" '
            f'fill="{c["celula"]}" stroke="{c["borda"]}"/>'
        )
        self.codigo(tokens, X_CELULA + 14, y + 25)
        return y + 38

    def saida(self, n: int, y: float) -> None:
        self.texto("mono", f"Out[{n}]:", X_CELULA - 12, y, 13.5, "destaque", "f")

    def fim(self) -> str:
        return "".join(self.partes) + "</svg>"


def hero(fontes: dict, cores: dict, perfil: dict, vivos: dict) -> str:
    linhas = perfil["info"] + [
        ["projetos", f"{vivos['n_repos']} públicos, última atividade em {vivos['ultima']}"],
    ]
    alt = f"{perfil['nome']}. {perfil['titulo']}. " + ". ".join(f"{k}: {v}" for k, v in linhas)
    css = (
        "<style>.k{animation:k 1.2s steps(1) infinite}@keyframes k{50%{opacity:0}}"
        "@media (prefers-reduced-motion:reduce){.k{animation:none}}</style>"
    )
    altura = 500
    t = Tela(fontes, cores, altura, alt, css)
    c = cores

    # Barra do notebook.
    t.add(f'<path d="M1 10a9 9 0 0 1 9-9h{LARGURA - 20}a9 9 0 0 1 9 9v34H1z" fill="{c["barra"]}"/>')
    t.add(f'<line x1="1" y1="44" x2="{LARGURA - 1}" y2="44" stroke="{c["borda"]}"/>')
    t.texto("mono", "pedro_ostroski.ipynb", 24, 28, 14, "texto")
    t.add(f'<circle cx="{LARGURA - 34}" cy="23" r="5" fill="{c["ok"]}"/>')
    t.texto("mono", "Python 3 | pronto", LARGURA - 48, 28, 13.5, "suave", "f")

    # Célula de texto.
    t.texto("bold", perfil["nome"], X_CELULA, 112, 54, "texto")
    t.texto("inter", perfil["titulo"], X_CELULA + 1, 148, 21, "suave")

    # Célula de código e saída.
    y = t.entrada(
        1,
        [("pedro", "texto"), (".", "suave"), ("info", "entrada"), ("()", "suave")],
        178,
    )
    y += 32
    t.saida(1, y)
    t.texto("mono", "<class 'CientistaDeDados'>", X_CELULA + 14, y, 15, "suave")
    for chave, valor in linhas:
        y += 30
        t.texto("mono", chave, X_CELULA + 14, y, 15, "destaque")
        t.texto("mono", valor, X_CELULA + 124, y, 15, "texto")

    # Próxima célula, à espera de quem chega.
    y += 32
    t.texto("mono", "In [ ]:", X_CELULA - 12, y + 6, 13.5, "entrada", "f")
    t.add(f'<rect class="k" x="{X_CELULA + 14}" y="{y - 9}" width="9" height="19" fill="{c["destaque"]}"/>')
    return t.fim()


def oraculo(fontes: dict, cores: dict, perfil: dict, vivos: dict) -> str:
    alt = "Resultados do Oráculo do Mestre. " + ". ".join(f"{v}: {' '.join(r)}" for v, r in perfil["oraculo"])
    t = Tela(fontes, cores, 204, alt)
    y = t.entrada(
        2,
        [("oraculo", "texto"), (".", "suave"), ("avaliar", "entrada"), ("(", "suave"), ("sem_vazamento", "texto"), ("=", "suave"), ("True", "destaque"), (")", "suave")],
        18,
    )
    t.saida(2, y + 34)
    col = (X_FIM - X_CELULA) / 4
    for i, (valor, rotulo) in enumerate(perfil["oraculo"]):
        x = X_CELULA + col * i + (14 if i == 0 else 16)
        if i:
            t.add(f'<line x1="{X_CELULA + col * i:.1f}" y1="{y + 16}" x2="{X_CELULA + col * i:.1f}" y2="{y + 132}" stroke="{cores["borda"]}"/>')
        t.texto("bold", valor, x, y + 52, 29, "destaque")
        for k, linha in enumerate(rotulo):
            t.texto("inter", linha, x, y + 86 + k * 22, 14.5, "suave")
    return t.fim()


def placar(fontes: dict, cores: dict, perfil: dict, vivos: dict) -> str:
    projetos = perfil["projetos"]
    alt = "Projetos. " + ". ".join(
        f"{p['nome']}: {p['tarefa']}, {p['metrica']} {p['valor']}, {p['autoria']}, CI {vivos['ci'][p['repo']]}" for p in projetos
    )
    altura_linha = 40
    y0 = 18 + 38 + 22
    altura = y0 + altura_linha * (len(projetos) + 1) + 22
    t = Tela(fontes, cores, altura, alt)
    t.entrada(3, [("projetos", "texto"), ("[", "suave"), ("colunas", "texto"), ("]", "suave")], 18)
    t.saida(3, y0 + 26)
    c = cores
    # x de cada coluna: nome, tarefa, métrica, valor (borda direita), autoria, CI.
    xs = {"i": X_CELULA + 10, "nome": X_CELULA + 34, "tarefa": X_CELULA + 208, "metrica": X_CELULA + 378, "valor": X_CELULA + 554, "autoria": X_CELULA + 574, "ci": X_CELULA + 648}
    cab = [("nome", "projeto"), ("tarefa", "tarefa"), ("metrica", "métrica"), ("autoria", "autoria"), ("ci", "CI")]
    for k, rotulo in cab:
        t.texto("bold", rotulo, xs[k], y0 + 26, 14, "texto")
    t.texto("bold", "valor", xs["valor"], y0 + 26, 14, "texto", "f")
    t.add(f'<line x1="{X_CELULA}" y1="{y0 + altura_linha}" x2="{X_FIM}" y2="{y0 + altura_linha}" stroke="{c["suave"]}"/>')
    for i, p in enumerate(projetos):
        topo = y0 + altura_linha * (i + 1)
        if i % 2 == 0:
            t.add(f'<rect x="{X_CELULA}" y="{topo + .5}" width="{X_FIM - X_CELULA}" height="{altura_linha - 1}" fill="{c["listra"]}"/>')
        y = topo + 26
        t.texto("mono", str(i), xs["i"], y, 13.5, "suave")
        t.texto("inter", p["nome"], xs["nome"], y, 14.5, "texto")
        t.texto("inter", p["tarefa"], xs["tarefa"], y, 14.5, "suave")
        t.texto("inter", p["metrica"], xs["metrica"], y, 14.5, "suave")
        t.texto("mono_bold", p["valor"], xs["valor"], y, 15, "texto", "f")
        t.texto("inter", p["autoria"], xs["autoria"], y, 14.5, "suave")
        estado = vivos["ci"][p["repo"]]
        cor = {"passou": "ok", "falhou": "erro"}.get(estado)
        x_ci = xs["ci"]
        if cor:
            t.add(f'<circle cx="{x_ci + 5}" cy="{y - 5}" r="4.5" fill="{c[cor]}"/>')
            t.texto("inter", estado, x_ci + 16, y, 14.5, "texto")
        else:
            t.texto("inter", estado, x_ci, y, 14.5, "suave")
    return t.fim()


def linguagens(fontes: dict, cores: dict, perfil: dict, vivos: dict) -> str:
    dados = vivos["linguagens"][:6]
    alt = "Repositórios públicos que usam cada linguagem. " + ", ".join(f"{n}: {q}" for n, q in dados)
    altura_linha = 34
    y0 = 18 + 38 + 28
    altura = y0 + 28 + altura_linha * len(dados) + 18
    t = Tela(fontes, cores, altura, alt)
    t.entrada(
        4,
        [("repos", "texto"), (".", "suave"), ("linguagens", "texto"), (".", "suave"), ("value_counts", "entrada"), ("()", "suave"), (".", "suave"), ("plot", "texto"), (".", "suave"), ("barh", "entrada"), ("()", "suave")],
        18,
    )
    t.saida(4, y0 + 8)
    t.texto("inter", f"Em quantos dos {vivos['n_repos']} repositórios públicos cada linguagem aparece", X_CELULA + 14, y0 + 8, 15, "texto")
    x_barra = X_CELULA + 180
    larg_max = X_FIM - x_barra - 50
    maior = max(q for _, q in dados)
    for i, (nome, q) in enumerate(dados):
        y = y0 + 28 + altura_linha * i
        t.texto("inter", nome, x_barra - 14, y + 19, 14.5, "suave", "f")
        w = larg_max * q / maior
        # Base reta no eixo, ponta arredondada de 4px.
        t.add(
            f'<path d="M{x_barra} {y + 5}h{w - 4:.1f}a4 4 0 0 1 4 4v8a4 4 0 0 1-4 4H{x_barra}z" fill="{cores["destaque"]}"/>'
        )
        t.texto("mono_bold", str(q), x_barra + w + 10, y + 19, 14.5, "texto")
    t.add(f'<line x1="{x_barra}" y1="{y0 + 26}" x2="{x_barra}" y2="{y0 + 28 + altura_linha * len(dados)}" stroke="{cores["suave"]}"/>')
    return t.fim()


def ferramentas(fontes: dict, cores: dict, perfil: dict, vivos: dict) -> str:
    etapas = perfil["ferramentas"]
    diretas = "; ".join(f"{e['etapa']}: " + ", ".join(n for n, d in e["itens"] if d) for e in etapas)
    equipe = ", ".join(n for e in etapas for n, d in e["itens"] if not d)
    alt = f"Ferramentas de uso direto. {diretas}. Em projeto de equipe: {equipe}."
    linhas = max(len(e["itens"]) for e in etapas)
    y0 = 18 + 38 + 34
    altura = y0 + 34 + linhas * 32 + 58
    t = Tela(fontes, cores, altura, alt)
    t.entrada(5, [("pedro", "texto"), (".", "suave"), ("ferramentas", "texto"), ("[", "suave"), ('"por_etapa"', "texto_codigo"), ("]", "suave")], 18)
    t.saida(5, y0)
    col = (X_FIM - X_CELULA - 10) / 5
    c = cores
    for i, e in enumerate(etapas):
        x = X_CELULA + 10 + col * i
        t.texto("mono_bold", e["etapa"], x, y0, 13.5, "destaque")
        t.add(f'<line x1="{x:.1f}" y1="{y0 + 12}" x2="{x + col - 22:.1f}" y2="{y0 + 12}" stroke="{c["borda"]}"/>')
        for k, (nome, direto) in enumerate(e["itens"]):
            y = y0 + 42 + k * 32
            if direto:
                t.add(f'<circle cx="{x + 4:.1f}" cy="{y - 5}" r="4" fill="{c["texto"]}"/>')
            else:
                t.add(f'<circle cx="{x + 4:.1f}" cy="{y - 5}" r="3.4" fill="none" stroke="{c["suave"]}" stroke-width="1.4"/>')
            t.texto("inter", nome, x + 16, y, 15, "texto" if direto else "suave")
    yl = altura - 24
    x = X_CELULA + 10
    t.add(f'<circle cx="{x + 4}" cy="{yl - 5}" r="4" fill="{c["texto"]}"/>')
    fim = t.texto("inter", "uso direto", x + 16, yl, 14, "suave")
    t.add(f'<circle cx="{fim + 26:.1f}" cy="{yl - 5}" r="3.4" fill="none" stroke="{c["suave"]}" stroke-width="1.4"/>')
    t.texto("inter", "em projeto de equipe", fim + 38, yl, 14, "suave")
    return t.fim()


def api(caminho: str):
    req = urllib.request.Request(f"https://api.github.com/{caminho}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "gerador-de-perfil")
    token = os.environ.get("GH_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def estado_ci(usuario: str, repo: str) -> str:
    """Último resultado do workflow de CI na branch principal."""
    fluxos = api(f"repos/{usuario}/{repo}/actions/workflows")["workflows"]
    ci = [f for f in fluxos if f["state"] == "active" and Path(f["path"]).stem.lower() in ("ci", "ci-cd", "cicd", "tests", "test")]
    if not ci:
        return "sem CI"
    arquivo = Path(ci[0]["path"]).name
    runs = api(f"repos/{usuario}/{repo}/actions/workflows/{arquivo}/runs?branch=main&status=completed&per_page=1")["workflow_runs"]
    if not runs:
        return "sem CI"
    return "passou" if runs[0]["conclusion"] == "success" else "falhou"


def coletar(perfil: dict) -> dict:
    usuario = perfil["usuario"]
    # Rota pública: repositório privado nunca entra nas contas nem nas imagens.
    repos = api(f"users/{usuario}/repos?per_page=100&type=owner")
    repos = [r for r in repos if not r["fork"] and r["name"].lower() != usuario.lower()]
    contagem = Counter()
    for r in repos:
        contagem.update(api(f"repos/{usuario}/{r['name']}/languages").keys())
    ultima = max(datetime.fromisoformat(r["pushed_at"].replace("Z", "+00:00")) for r in repos)
    return {
        "n_repos": len(repos),
        "ultima": ultima.strftime("%d/%m/%Y"),
        "linguagens": sorted(contagem.items(), key=lambda kv: (-kv[1], kv[0])),
        "ci": {p["repo"]: estado_ci(usuario, p["repo"]) for p in perfil["projetos"]},
    }


def main() -> None:
    perfil = json.loads((RAIZ / "dados" / "perfil.json").read_text(encoding="utf-8"))
    vivos = coletar(perfil)
    print(json.dumps(vivos, ensure_ascii=False, indent=2))
    pasta = RAIZ / "scripts" / "fontes"
    fontes = {
        "inter": Fonte(pasta / "inter.ttf"),
        "bold": Fonte(pasta / "inter-bold.ttf"),
        "mono": Fonte(pasta / "mono.ttf"),
        "mono_bold": Fonte(pasta / "mono-bold.ttf"),
    }
    saida = RAIZ / "assets"
    saida.mkdir(exist_ok=True)
    for tema, cores in TEMAS.items():
        for nome, gerar in (("hero", hero), ("oraculo", oraculo), ("placar", placar), ("linguagens", linguagens), ("ferramentas", ferramentas)):
            (saida / f"{nome}-{tema}.svg").write_text(gerar(fontes, cores, perfil, vivos), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    try:
        main()
    except urllib.error.URLError as erro:
        # Falha de rede não pode sobrescrever as imagens atuais.
        raise SystemExit(f"Falha ao consultar o GitHub: {erro}") from erro
