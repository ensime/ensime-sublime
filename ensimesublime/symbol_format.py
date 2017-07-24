# coding: utf-8

"""
Functions for symbols formatting.
"""


def completion_to_suggest(completion):
    """Convert from a completion to a suggestion."""
    res = {
        # We use just the method name as completion
        "word": completion["name"],
        # We show the whole method signature in the popup
        "abbr": formatted_completion_sig(completion),
        # We show method result/field type in a sepatate column
        "menu": formatted_type(completion["typeInfo"]),
        # This is the signature that gets inserted
        "sig": formatted_completion_sig(completion, forInsertion=True)
    }
    resp = ("{}\t{:^32.30} {:>10}".format(res["word"], res["abbr"], res["menu"]), res["sig"])
    return resp


def type_to_show(tpe):
    if is_basic_type(tpe):
        return tpe["fullName"]
    signature = formatted_message_params(tpe)
    return_type = formatted_type(tpe)
    return "{} => {}".format(signature, return_type)


def is_basic_type(completion):
    return completion["typehint"] == "BasicTypeInfo"


def formatted_completion_sig(completion, forInsertion=False):
    """Regenerate signature for methods. Return just the name otherwise"""
    f_result = completion["name"]
    if is_basic_type(completion["typeInfo"]):
        # It's a raw type
        return f_result
    elif len(completion["typeInfo"]["paramSections"]) == 0:
        return f_result

    # It's a function type
    if not forInsertion:
        return u"{}{}".format(f_result, formatted_message_params(completion["typeInfo"]))
    else:
        return u"{}{}".format(f_result, formatted_insertion_params(completion["typeInfo"]))


def formatted_message_params(typeInfo):
    sections = typeInfo["paramSections"]
    f_sections = [formatted_param_section(ps) for ps in sections]
    return "".join(f_sections)


def formatted_type(typeInfo):
    """Use result type for methods. Return just the member type otherwise"""
    return typeInfo["name"] if is_basic_type(typeInfo) else typeInfo["resultType"]["name"]


def formatted_param_section(section):
    """Format a parameters list. Supports the implicit list"""
    implicit = "implicit " if section["isImplicit"] else ""
    s_params = [(p[0], formatted_param_type(p[1])) for p in section["params"]]
    return "({}{})".format(implicit, concat_params(s_params))


def formatted_insertion_params(typeInfo):
    sections = typeInfo["paramSections"]
    section_snippets = []
    i = 1
    for param_section in sections:
        param_snippets = []
        for param in param_section["params"]:
            name = param[0]
            tpe = formatted_param_type(param[1])
            param_snippets.append("${{{index}:{name}:{type}}}".format(index=i, name=name, type=tpe))
            i += 1
        section_snippets.append("(" + ", ".join(param_snippets) + ")")
    return "".join(section_snippets)


def concat_params(params):
    """Return list of params from list of (pname, ptype)."""
    name_and_types = [": ".join(p) for p in params]
    return ", ".join(name_and_types)


def formatted_param_type(ptype):
    """Return the short name for a type. Special treatment for by-name and var args"""
    pt_name = ptype["name"]
    if pt_name.startswith("<byname>"):
        pt_name = pt_name.replace("<byname>[", "=> ")[:-1]
    elif pt_name.startswith("<repeated>"):
        pt_name = pt_name.replace("<repeated>[", "")[:-1] + "*"
    return pt_name
