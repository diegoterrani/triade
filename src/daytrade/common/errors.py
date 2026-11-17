"""Erros de segurança. Falhar fechado: sem ordem quando houver dúvida."""


class SafetyError(RuntimeError):
    """A operação foi recusada por um trilho de segurança."""


class Disconnect(RuntimeError):
    """A fonte de dados ou a corretora ficou inacessível."""


class LiveGateError(SafetyError):
    """Modo live sem as duas travas (config e variável de ambiente)."""


class AlreadyFlat(SafetyError):
    """A corretora já estava zerada. Não reabre posição."""


class EntryRolledBack(SafetyError):
    """A entrada foi desfeita porque o stop não ficou registrado."""
