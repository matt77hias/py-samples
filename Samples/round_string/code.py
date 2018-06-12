def round_string(string, precision=2):
    assert(int(precision) >= 0)
    float(string)
    
    decimal_point = string.find('.')
    if decimal_point == -1:
        if precision == 0:
            return string
        return string + '.' + '0' * precision
    
    all_decimals = string[decimal_point+1:]
    nb_missing_decimals = precision - len(all_decimals)
    if nb_missing_decimals >= 0:
        if precision == 0:
            return string[:decimal_point]
        return string + '0' * nb_missing_decimals
    
    if int(all_decimals[precision]) < 5:
        if precision == 0:
            return string[:decimal_point]
        return string[:decimal_point+precision+1]
      
    sign = '-' if string[0] == '-' else '' 
    integer_part = abs(int(string[:decimal_point]))
    if precision == 0:
        return sign + str(integer_part + 1)
    decimals = str(int(all_decimals[:precision]) + 1)
    nb_missing_decimals = precision - len(decimals)
    if nb_missing_decimals >= 0:
        return sign + str(integer_part) + '.' + '0' * nb_missing_decimals + decimals
    return sign + str(integer_part + 1) + '.' + '0' * precision
    
