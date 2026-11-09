from decimal import Decimal, InvalidOperation

CONFIG = {
 "Rate.XP.Kill": ("杀怪经验", "倍", .1, 20, False),
 "Rate.XP.Quest": ("任务经验", "倍", .1, 20, False),
 "Rate.XP.Explore": ("探索经验", "倍", .1, 20, False),
 "Rate.Health": ("自然回血", "倍", .1, 20, False),
 "Rate.Mana": ("法力回复", "倍", .1, 20, False),
 "Rate.Energy": ("能量回复", "倍", .1, 20, False),
 "Rate.Drop.Money": ("金钱掉落", "倍", .1, 20, False),
 "StartPlayerLevel": ("新角色出生等级", "级", 1, 60, True),
 "StartPlayerMoney": ("新角色初始金钱", "铜币", 0, 100000000, True),
}

def validate(values, maximum=60):
    if not values or set(values)-set(CONFIG):
        raise ValueError("包含不允许调整的设置")
    result={}
    for key,value in values.items():
        _,_,lo,hi,integer=CONFIG[key]
        if key=="StartPlayerLevel": hi=min(hi,maximum)
        try: number=Decimal(str(value))
        except InvalidOperation: raise ValueError("请输入有效数字") from None
        if not number.is_finite() or number<Decimal(str(lo)) or number>Decimal(str(hi)):
            raise ValueError(f"{CONFIG[key][0]}须在 {lo}–{hi} 之间")
        if integer and number!=number.to_integral_value(): raise ValueError(f"{CONFIG[key][0]}须为整数")
        result[key]=int(number) if integer else float(number)
    return result
