class LongIdObfuscator:
    ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    BASE = len(ALPHABET)
    M = 1 << 64
    A = 1190494759
    B = 87234521
    A_INV = pow(A, -1, M)

    @classmethod
    def _to_unsigned(cls, value: int) -> int:
        return value & (cls.M - 1)

    @classmethod
    def _obfuscate(cls, id_val: int) -> int:
        x = cls._to_unsigned(id_val)
        return (x * cls.A + cls.B) % cls.M

    @classmethod
    def _deobfuscate(cls, x: int) -> int:
        return ((x - cls.B) % cls.M * cls.A_INV) % cls.M

    @classmethod
    def _encode_base(cls, n: int) -> str:
        if n == 0:
            return cls.ALPHABET[0]
        chars = []
        while n > 0:
            n, r = divmod(n, cls.BASE)
            chars.append(cls.ALPHABET[r])
        return "".join(reversed(chars))

    @classmethod
    def _decode_base_safe(cls, s: str) -> int | None:
        n = 0
        for c in s:
            idx = cls.ALPHABET.find(c)
            if idx == -1:
                return None
            n = n * cls.BASE + idx
        return n

    @classmethod
    def code_to_id(cls, code: str) -> int | None:
        x = cls._decode_base_safe(code)
        if x is None:
            return None
        return cls._deobfuscate(x)

    @classmethod
    def id_to_code(cls, id_val: int | None) -> str | None:
        if id_val is None:
            return None
        x = cls._obfuscate(id_val)
        return cls._encode_base(x)
