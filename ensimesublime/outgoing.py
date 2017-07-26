import json

from util import Pretty

DEFAULT_TIMEOUT = 300
COMPLETION_TIMEOUT = 5


class RpcRequest(object):

    def send_request(self, request, client, async):
        """Send a request to the server."""
        client.env.logger.debug('send_request: in')

        message = {'callId': client.call_id, 'req': request}
        client.call_options[client.call_id] = {'async': async}
        client.call_options[client.call_id].update(self.call_options())
        client.env.logger.info('send_request: %s', Pretty(message))
        client.send(json.dumps(message))

        call_id = client.call_id
        client.call_id += 1
        return call_id

    def run_in(self, env, async=False):
        call_id = self.send_request(self.json_repr(), env.client, async)
        if not async:
            timeout = getattr(self, 'timeout', DEFAULT_TIMEOUT)
            response = env.client.get_response(call_id, timeout=timeout)
            return response
        return None

    def json_repr(self):
        raise NotImplementedError

    def call_options(self):
        return {}


class ConnectionInfoRequest(RpcRequest):
    def __init__(self):
        super(ConnectionInfoRequest, self).__init__()

    def json_repr(self):
        return {"typehint": "ConnectionInfoReq"}


class TypeCheckFilesReq(RpcRequest):
    def __init__(self, filenames):
        super(TypeCheckFilesReq, self).__init__()
        self.filenames = list(filenames)

    def json_repr(self):
        return {"typehint": "TypecheckFilesReq",
                "files": self.filenames}


class ImportSuggestionsReq(RpcRequest):
    def __init__(self, pos, file, word, max_results=10):
        super(ImportSuggestionsReq, self).__init__()
        self.pos = pos
        self.file = file
        self.names = [word]
        self.max_results = max_results

    def json_repr(self):
        return {"point": self.pos,
                "maxResults": self.max_results,
                "names": self.names,
                "typehint": "ImportSuggestionsReq",
                "file": self.file}

    def call_options(self):
        return {'file_name': self.file}


class CompletionsReq(RpcRequest):
    def __init__(self, point, file, contents=None, max_results=100, case_sensitive=True, reLoad=False):
        super(CompletionsReq, self).__init__()
        self.point = point
        self.file_info = self._file_info(file, contents)
        self.case_sensitive = case_sensitive
        self.max_results = max_results
        self.reLoad = reLoad
        self.timeout = COMPLETION_TIMEOUT

    def _file_info(self, file, contents):
        """Message fragment for ENSIME ``fileInfo`` field, from current file."""
        file_info = {"file": file}
        if contents is not None:
            file_info.update({"contents": contents})
        return file_info

    def json_repr(self):
        return {"point": self.point, "maxResults": self.max_results,
                "typehint": "CompletionsReq",
                "caseSens": self.case_sensitive,
                "fileInfo": self.file_info,
                "reload": self.reLoad}


class SymbolAtPointReq(RpcRequest):
    def __init__(self, file, contents, pos):
        super(SymbolAtPointReq, self).__init__()
        self.file_info = self._file_info(file, contents)
        self.pos = pos

    def _file_info(self, file, contents):
        """Message fragment for ENSIME ``fileInfo`` field, from current file."""
        file_info = {"file": file}
        if contents is not None:
            file_info.update({"contents": contents})
        return file_info

    def json_repr(self):
        return {"typehint": "SymbolAtPointReq",
                "file": self.file_info,
                "point": self.pos}


class PublicSymbolSearchReq(RpcRequest):
    def __init__(self, search_terms, max_results=25):
        super(PublicSymbolSearchReq, self).__init__()
        self.search_terms = search_terms
        self.max_results = max_results

    def json_repr(self):
        return {"typehint": "PublicSymbolSearchReq",
                "keywords": self.search_terms,
                "maxResults": self.max_results}


class GenericAtPointReq(RpcRequest):
    def __init__(self, file, contents, pos, what):
        super(GenericAtPointReq, self).__init__()
        self.file_info = self._file_info(file, contents)
        self.pos_tag = "range" if what == "Type" else "point"
        self.pos = pos
        self.what = what

    def _file_info(self, file, contents):
        """Message fragment for ENSIME ``fileInfo`` field, from current file."""
        file_info = {"file": file}
        if contents is not None:
            file_info.update({"contents": contents})
        return file_info

    def json_repr(self):
        return {"typehint": "{}AtPointReq".format(self.what),
                "file": self.file_info,
                "{}".format(self.pos_tag): {"from": self.pos, "to": self.pos}}


class TypeAtPointReq(GenericAtPointReq):
    def __init__(self, file, contents, pos):
        super(TypeAtPointReq, self).__init__(file, contents, pos, "Type")


class DocUriAtPointReq(GenericAtPointReq):
    def __init__(self, file, contents, pos):
        super(DocUriAtPointReq, self).__init__(file, contents, pos, "DocUri")

    def call_options(self):
        return {"browse": True}


# ########################## Refactor Requests ##########################
class RefactorRequest(RpcRequest):
    def __init__(self):
        super(RefactorRequest, self).__init__()

    def run_in(self, env, async=False):
        call_id = self.send_refactor_request(self.json_repr(), env.client, async)
        if not async:
            got_response = env.client.get_response(call_id)
            return got_response
        return True

    def send_refactor_request(self, req, client, async):
        """Send a refactor request to the Ensime server.

        The `ref_params` field will always have a field `type`.
        """
        ref_type = req['ref_type']
        ref_params = req['ref_params']
        ref_options = req['ref_options']
        request = {
            "typehint": ref_type,
            "procId": client.refactor_id,
            "params": ref_params
        }
        f = ref_params["file"]
        client.refactorings[client.refactor_id] = f
        client.refactor_id += 1
        request.update(ref_options)
        return self.send_request(request, client, async)


class AddImportRefactorDesc(RefactorRequest):
    def __init__(self, file, name):
        super(AddImportRefactorDesc, self).__init__()
        self.file = file
        self.name = name

    def json_repr(self):
        return {"ref_type": "RefactorReq",
                "ref_params": {"typehint": "AddImportRefactorDesc",
                               "file": self.file,
                               "qualifiedName": self.name},
                "ref_options": {"interactive": False}}


class OrganiseImports(RefactorRequest):
    def __init__(self, file):
        super(OrganiseImports, self).__init__()
        self.file = file

    def json_repr(self):
        return {"ref_type": "RefactorReq",
                "ref_params": {"typehint": "OrganiseImportsRefactorDesc",
                               "file": self.file,
                               },
                "ref_options": {"interactive": False}}


class RenameRefactorDesc(RefactorRequest):
    def __init__(self, new_name, start, end, file):
        super(RenameRefactorDesc, self).__init__()
        self.new_name = new_name
        self.start = start
        self.end = end
        self.file = file

    def json_repr(self):
        return {"ref_type": "RefactorReq",
                "ref_params": {"typehint": "RenameRefactorDesc",
                               "newName": self.new_name,
                               "start": self.start,
                               "end": self.end,
                               "file": self.file,
                               },
                "ref_options": {"interactive": False}}


class InlineLocalRefactorDesc(RefactorRequest):
    def __init__(self, start, end, file):
        super(InlineLocalRefactorDesc, self).__init__()
        self.start = start
        self.end = end
        self.file = file

    def json_repr(self):
        return {"ref_type": "RefactorReq",
                "ref_params": {"typehint": "InlineLocalRefactorDesc",
                               "start": self.start,
                               "end": self.end,
                               "file": self.file,
                               },
                "ref_options": {"interactive": False}}


# ########################## Debug Requests ##########################
class DebugSetBreakReq(RpcRequest):
    def __init__(self, file, line, max_results=10):
        super(DebugSetBreakReq, self).__init__()
        self.file = file
        self.line = line
        self.max_results = max_results

    def json_repr(self):
        return {"line": self.line,
                "maxResults": self.max_results,
                "typehint": "DebugSetBreakReq",
                "file": self.file}


class DebugClearAllBreaksReq(RpcRequest):
    def __init__(self):
        super(DebugClearAllBreaksReq, self).__init__()

    def json_repr(self):
        return {"typehint": "DebugClearAllBreaksReq"}


class DebugAttachReq(RpcRequest):
    def __init__(self, hostname, port):
        super(DebugAttachReq, self).__init__()
        self.hostname = hostname
        self.port = port

    def json_repr(self):
        return {"typehint": "DebugAttachReq",
                "hostname": self.hostname,
                "port": self.port}


class DebugBacktraceReq(RpcRequest):
    def __init__(self, thread_id, index=0, count=100):
        super(DebugBacktraceReq, self).__init__()
        self.thread_id = thread_id
        self.index = index
        self.count = count

    def json_repr(self):
        return {"typehint": "DebugBacktraceReq",
                "threadId": self.thread_id,
                "index": self.index, "count": self.count}


class SimpleDebugRequest(RpcRequest):
    def __init__(self, thread_id, what):
        super(SimpleDebugRequest, self).__init__()
        self.thread_id = thread_id
        self.what = what

    def json_repr(self):
        return {"typehint": "{}Req".format(self.what),
                "threadId": self.thread_id}


class DebugContinueRequest(SimpleDebugRequest):
    def __init__(self, thread_id):
        super(DebugContinueRequest, self).__init__(thread_id, "DebugContinue")


class DebugStepReq(SimpleDebugRequest):
    def __init__(self, thread_id):
        super(DebugStepReq, self).__init__(thread_id, "DebugStep")


class DebugStepOutReq(SimpleDebugRequest):
    def __init__(self, thread_id):
        super(DebugStepOutReq, self).__init__(thread_id, "DebugStepOut")


class DebugNextReq(SimpleDebugRequest):
    def __init__(self, thread_id):
        super(DebugNextReq, self).__init__(thread_id, "DebugNext")
