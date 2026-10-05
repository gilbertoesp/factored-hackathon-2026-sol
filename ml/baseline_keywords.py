"""M04: línea base por palabras clave, sin aprendizaje.

Cada clase tiene una lista de patrones por idioma. Gana la clase con más
patrones encontrados; en empate, la primera de CLASES. Si ningún patrón aparece,
la línea base se abstiene ("ambigua"), que es lo que haría pedir una aclaración.

Sirve como piso de comparación para el clasificador aprendido (M05) y el LLM
zero-shot (M06): mismas clases, mismo set de prueba, mismas métricas.
"""
import re
import unicodedata

from intents import ABSTENCION, CLASES

PATRONES = {
    "es": {
        "cargo_no_reconocido": [
            r"no (lo |la |los |las )?reconozc", r"no reconoc", r"desconozc", r"desconocid",
            r"no (lo |la )?(hice|realice|efectue|autorice)", r"no he (hecho|realizado|autorizado)",
            r"no fui yo", r"yo no (hice|realice|retire|saque|compre)", r"sin mi (autorizacion|permiso|consentimiento)",
            r"fraud", r"clon", r"alguien (mas )?(uso|utilizo|saco|retiro|esta usando)", r"no es mi[oa]",
            r"no recuerdo (haber|ese|esa|este|esta)", r"que es (este|ese|esta|esa) (cargo|cobro|pago|retiro|debito)",
        ],
        "cobro_indebido": [
            r"dos veces", r"doble", r"duplicad", r"dobl", r"repetid", r"comision", r"tarifa", r"recargo",
            r"(cobro|cargo|costo) (extra|adicional|de mas)", r"de mas", r"cobro indebido",
            r"por que (me )?(cobraron|cobran|cobro)", r"me (cobraron|cobran) (por|una|un|al)",
        ],
        "otro_reclamo": [
            r"no funciona", r"no sirve", r"dejo de funcionar", r"fall(o|a|ida|ando)", r"\berror\b",
            r"no (ha |me )?lleg(o|ado|a)", r"se (trago|quedo con|retuvo)", r"no (puedo|pude|me deja)",
            r"no (se )?(refleja|aparece|actualiz)", r"no (pasa|paso|lee)", r"sin contacto", r"rechaz",
        ],
        "fuera_de_alcance": [
            r"como (puedo|hago|cambio|activo|solicito|pido|cierro|actualizo)", r"cuanto (tarda|demora|tiempo)",
            r"cuando (llega|llegara|recibire)", r"tipo de cambio", r"tasa de cambio", r"activar",
            r"cambiar (mi |el |de )?(pin|nip|clave|direccion|nombre|datos)", r"\blimite", r"cerrar (mi |la )?cuenta",
            r"\bedad\b", r"(perdi|robaron|perdida|robada|extravi)", r"(pedir|solicitar|ordenar) (una |mi )?tarjeta",
            r"cuantos anos", r"puedo (cambiar|abrir|pedir|tener)",
        ],
    },
    "pt": {
        "cargo_no_reconocido": [
            r"nao (o |a )?reconhec", r"desconhec", r"nao (fiz|realizei|efetuei|autorizei)",
            r"nao fui eu", r"eu nao (fiz|realizei|saquei|comprei|retirei)", r"sem (a )?minha (autorizacao|permissao)",
            r"fraud", r"clon", r"alguem (usou|utilizou|sacou|retirou|esta usando)", r"nao e meu|nao e minha",
            r"nao (me )?lembro de", r"o que e (esse|essa|este|esta) (cobranca|pagamento|saque|debito|transacao)",
        ],
        "cobro_indebido": [
            r"duas vezes", r"dobro", r"duplicad", r"dupl", r"repetid", r"taxa", r"tarifa", r"comissao", r"encargo",
            r"(cobranca|custo|valor) (extra|adicional|a mais)", r"a mais", r"cobranca indevida",
            r"por que (fui|me|estou sendo) (cobrad|cobrar)", r"fui cobrad[oa] (por|uma|um)",
        ],
        "otro_reclamo": [
            r"nao funciona", r"parou de funcionar", r"falh(ou|a|ando)", r"\berro\b", r"nao chegou",
            r"(engoliu|reteve|ficou com)", r"nao (consigo|consegui|me deixa)", r"nao (aparece|atualiz|reflet)",
            r"nao (passa|passou|le)", r"por aproximacao", r"sem contato", r"recus",
        ],
        "fuera_de_alcance": [
            r"como (posso|faco|altero|ativo|solicito|peco|encerro|atualizo|mudo)", r"quanto tempo", r"quando (chega|vou receber)",
            r"taxa de cambio", r"cambio", r"ativar", r"(alterar|mudar|trocar) (meu |minha |o |a |de )?(pin|senha|endereco|nome|dados)",
            r"\blimite", r"(encerrar|fechar) (minha |a )?conta", r"\bidade\b", r"(perdi|roubaram|perdido|roubado|extravi)",
            r"(pedir|solicitar|encomendar) (um |meu )?cartao", r"quantos anos", r"posso (alterar|abrir|pedir|ter)",
        ],
    },
    "en": {
        "cargo_no_reconocido": [
            r"(don'?t|do not|didn'?t|did not) (recogni[sz]e|make|do|authori[sz]e)", r"not recogni[sz]e", r"unrecogni[sz]ed",
            r"unknown", r"unfamiliar", r"wasn'?t me", r"not mine", r"fraud", r"someone (else )?(used|is using|made|withdrew|took)",
            r"without my (permission|authori[sz]ation|knowledge)", r"(don'?t|do not) remember", r"what is this (charge|payment|withdrawal|debit)",
        ],
        "cobro_indebido": [
            r"twice", r"double", r"duplicat", r"two times", r"\bfee", r"extra charge", r"additional charge", r"charged (extra|more|a|an|for)",
            r"why (was|am|did) i (charged|being charged|get charged)", r"overcharg",
        ],
        "otro_reclamo": [
            r"(not|n'?t|stopped) work", r"fail", r"\berror\b", r"(hasn'?t|has not|not|didn'?t) (arrived|received|show|gone through|updat)",
            r"(swallowed|ate|kept) my card", r"(can'?t|cannot|unable|won'?t)", r"contactless", r"declin",
        ],
        "fuera_de_alcance": [
            r"how (do|can|long|old|many)", r"when will", r"exchange rate", r"activat", r"change (my )?(pin|address|name|details)",
            r"\blimit", r"(close|delete|terminate) (my )?account", r"\bage\b", r"(lost|stolen)", r"order (a |my )?(new )?card",
            r"(can|may) i (change|open|order|get|have)",
        ],
    },
}

_COMPILADOS = {
    idioma: {clase: [re.compile(p) for p in patrones] for clase, patrones in por_clase.items()}
    for idioma, por_clase in PATRONES.items()
}


def normalizar(texto):
    """Minúsculas y sin acentos, para que los patrones no dependan de la ortografía."""
    plano = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return " ".join(plano.lower().split())


def puntajes(texto, idioma):
    plano = normalizar(texto)
    return {clase: sum(bool(p.search(plano)) for p in _COMPILADOS[idioma][clase]) for clase in CLASES}


def clasificar(texto, idioma):
    """Clase con más patrones; ABSTENCION si no aparece ninguno."""
    p = puntajes(texto, idioma)
    mejor = max(CLASES, key=lambda c: p[c])  # max conserva el primero en empate: orden de CLASES
    return mejor if p[mejor] > 0 else ABSTENCION
