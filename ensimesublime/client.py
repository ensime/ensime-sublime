# coding: utf-8
import sublime

import time
import json
from threading import Thread

import websocket
# from functools import partial as bind

from protocol import ProtocolHandler
from util import catch, Pretty
from errors import LaunchError
from outgoing import ConnectionInfoRequest
from config import gconfig
from debugger import DebugHandler


class EnsimeClient(ProtocolHandler, DebugHandler):
    """An ENSIME client for a project configuration path (``.ensime``).

    This is a base class with an abstract ProtocolHandler – you will
    need to provide a concrete one.

    Once constructed, a client instance can either connect to an existing
    ENSIME server or launch a new one with a call to the ``setup()`` method.

    Communication with the server is done over a websocket (`self.ws`). Messages
    are sent to the server in the calling thread, while messages are received on
    a separate background thread and enqueued in `self.queue` upon receipt.

    Each call to the server contains a `callId` field with an integer ID,
    generated from `self.call_id`. Responses echo back the `callId` field so
    that appropriate handlers can be invoked.

    Responses also contain a `typehint` field in their `payload` field, which
    contains the type of the response. This is used to key into `self.handlers`,
    which stores the a handler per response type.
    """

    def __init__(self, parent_environment, launcher):
        super(EnsimeClient, self).__init__()
        self.launcher = launcher
        self.env = parent_environment
        self.env.logger.debug('__init__: in')

        self.ws = None
        self.ensime = None
        self.ensime_server = None

        self.call_id = 1
        self.call_options = {}
        self.refactor_id = 1
        self.refactorings = {}
        self.connection_timeout = self.env.settings.get("timeout_connection", 20)

        # Map for messages received from the ensime server.
        self.responses = {}
        # By default, don't connect to server more than once
        self.number_try_connection = 1

        self.debug_thread_id = None

        # status
        self.running = True  # queue poll is running
        self.connected = False  # connected to ensime server through websocket
        self.analyzer_ready = False
        self.indexer_ready = False

        thread = Thread(name='queue-poller', target=self.queue_poll)
        thread.daemon = True
        thread.start()

    def queue_poll(self, sleep_t=0.5):
        """Put new messages in the map as they arrive.
        Since putting a value in a map is an atomic operation,
        existence of a certain key and retrieval can be done
        from a separate thread by the client.
        Value of sleep is low to improve responsiveness.
        """
        while self.running:
            if self.ws is not None:
                def log_and_close(msg):
                    if self.connected:
                        self.env.logger.error('Websocket exception', exc_info=True)
                        self.env.logger.warning("Forcing shutdown. Check server log to see what happened.")
                        # Stop everything.
                        self.shutdown_server()
                        self._display_ws_warning()

                with catch(websocket.WebSocketException, log_and_close):
                    result = self.ws.recv()
                    if result:
                        try:
                            _json = json.loads(result)
                        except json.JSONDecodeError as e:
                            self.env.logger.error(e.msg)
                        else:
                            # Watch if it has a callId
                            call_id = _json.get("callId")

                            def handle_now():
                                if _json["payload"]:
                                    self.handle_incoming_response(call_id, _json["payload"])

                            def handle_later():
                                self.responses[call_id] = _json

                            if call_id is None:
                                handle_now()
                            else:
                                call_opt = self.call_options.get(call_id)
                                if call_opt and call_opt['async']:
                                    handle_now()
                                else:
                                    handle_later()
                    else:
                        time.sleep(sleep_t)

    def connect_when_ready(self, timeout, fallback):
        """Given a maximum timeout, waits for the http port to be written.
        Tries to connect to the websocket if it's written.
        If it fails cleans up by calling fallback. Ideally, should stop ensime
        process if connection wasn't established.
        """
        if not self.ws:
            while not self.ensime.is_ready() and (timeout > 0):
                time.sleep(1)
                timeout -= 1
            if self.ensime.is_ready():
                self.connected = self.connect_ensime_server()

            if not self.connected:
                fallback()
                self.env.logger.info("Couldn't connect to the server waited to long :(")
        else:
            self.env.logger.info("Already connected.")

    def setup(self):
        """Setup the client. Starts the enisme process using launcher
        and connects to it through websocket"""
        def initialize_ensime():
            if not self.ensime:
                self.env.logger.info("----Initialising server----")
                try:
                    self.ensime = self.launcher.launch()
                except LaunchError as err:
                    self.env.logger.error(err)
            return bool(self.ensime)

        # True if ensime is up, otherwise False
        self.running = initialize_ensime()
        if self.running:
            connect_when_ready_thread = Thread(target=self.connect_when_ready,
                                               args=(self.connection_timeout, self.teardown))
            connect_when_ready_thread.daemon = True
            connect_when_ready_thread.start()

        return self.running

    def _display_ws_warning(self):
        warning = "A WS exception happened, 'ensime-sublime' has been disabled. " +\
            "For more information, have a look at the logs in `.ensime_cache`"
        sublime.error_message(warning)

    def send(self, msg):
        """Send something to the ensime server."""
        def reconnect(e):
            self.env.logger.error('send error, reconnecting...')
            self.connect_ensime_server()
            if self.ws:
                self.ws.send(msg + "\n")

        self.env.logger.debug('send: in')
        if self.ws is not None:
            with catch(websocket.WebSocketException, reconnect):
                self.env.logger.debug('send: sending JSON on WebSocket')
                self.ws.send(msg + "\n")

    def get_response(self, call_id, timeout):
        """Gets a response with the specified call_id.
        Waits for the response to appear in the `responses` map for time specified by timeout.
        Returns the payload or None based on wether a response for that call_id was found."""
        start, now = time.time(), time.time()
        while (call_id not in self.responses) and (now - start) < timeout:
                time.sleep(0.5)
                now = time.time()
        if call_id not in self.responses:
            print(self.responses)
            self.env.logger.warning('no reply from server for %ss', timeout)
            return None
        result = self.responses[call_id]
        self.env.logger.debug('result received\n%s', Pretty(result))
        if result["payload"]:
            self.handle_incoming_response(call_id, result["payload"])
        del self.responses[call_id]
        return result["payload"]

    def connect_ensime_server(self):
        """Start initial connection with the server.
        Return True if the connection info is received
        else returns False"""
        self.env.logger.debug('connect_ensime_server: in')

        def disable_completely(e):
            if e:
                self.env.logger.error('connection error: %s', e, exc_info=True)
            self.shutdown_server()
            self.env.logger.info("Server was shutdown.")
            self._display_ws_warning()

        if self.running and self.number_try_connection:
            if not self.ensime_server:
                port = self.ensime.http_port()
                uri = "websocket"
                self.ensime_server = gconfig['ensime_server'].format(port, uri)
            with catch(websocket.WebSocketException, disable_completely):
                # Use the default timeout (no timeout).
                options = {"subprotocols": ["jerky"]}
                options['enable_multithread'] = True
                self.env.logger.info("About to connect to %s with options %s",
                                     self.ensime_server, options)
                self.ws = websocket.create_connection(self.ensime_server, **options)
            self.number_try_connection -= 1
            got_response = ConnectionInfoRequest().run_in(self.env)  # confirm response
            return bool(got_response is not None)
        else:
            # If it hits this, number_try_connection is 0
            disable_completely(None)
        return False

    def shutdown_server(self):
        """Shut down the ensime process if it is running and
        uncolorizes the open views in the editor.
        Does not change the client's running status."""
        self.env.logger.debug('shutdown_server: in')
        self.connected = False
        if self.ensime:
            self.ensime.stop()
            self.env.logger.info('Server shutdown.')
        self.env.editor.uncolorize_all()

    def teardown(self):
        """Shutdown down the client. Stop the server if connected.
        This stops the loop receiving responses from the websocket."""
        self.env.logger.debug('teardown: in')
        self.running = False
        self.shutdown_server()
