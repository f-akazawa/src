import sys

import tornado.httpserver
import tornado.ioloop
import tornado.iostream
import tornado.web
import tornado.httpclient
import redis

r = redis.Redis(host="127.0.0.1", port=6379, db=0)
r.flushall() #既にある全データ削除
class ProxyHandler(tornado.web.RequestHandler):
    @tornado.web.asynchronous
    def setCache(self, response):
        r.rpush(self.request.uri, response.code)    #レスポンスコード
        for header in ('Date', 'Cache-Control', 'Server', 'Content-Type', 'Location'):
            v = response.headers.get(header)
            if v:
                r.rpush(self.request.uri, header)   #ヘッダー名
                r.rpush(self.request.uri, v)        #ヘッダー情報
                break                   #3/15修正
        r.rpush(self.request.uri, response.body)    #内容
        r.expire(self.request.uri, 100)         #１００秒でキャッシュを消す
        print ("cache !!")

    @tornado.web.asynchronous
    def get(self):
        def handle_response(response):
            #プロキシサーバが要求先サーバから取ってきたコンテンツを処理する。
            if response.error and not isinstance(response.error,tornado.httpclient.HTTPError):
                self.set_status(500)
                self.write('Internal server error:\n' + str(response.error))
                self.finish()
            else:
                self.set_status(response.code)
                for header in ('Date', 'Cache-Control', 'Server', 'Content-Type', 'Location'):
                    v = response.headers.get(header)
                    if v:
                        self.set_header(header, v)
                if response.body:
                    self.write(response.body)
                self.finish()

                # アクセスするページのキャッシュがない場合、キャッシュする
                if not r.exists(self.request.uri):
                    self.setCache(response)

        def getCache(response):
            self.set_status(int(response[0]))
            if response[2]:
                self.set_header(response[1], response[2])
            if response[3]:
                self.write(response[3])
            self.finish()
        
        #アクセスページのキャッシュがある場合、その内容を返す
        if r.exists(self.request.uri):
            getCache(r.lrange(self.request.uri,0,-1))
            print ("return cache")
        else:
            #キャッシュが無い場合、プロキシ内でクライアントを作り、サーバにアクセスさせる
            req = tornado.httpclient.HTTPRequest(
                url=self.request.uri,
                method=self.request.method, body=self.request.body,
                headers=self.request.headers, follow_redirects=False,
                allow_nonstandard_methods=True)
            client = tornado.httpclient.AsyncHTTPClient()
            try:
                #コールバック関数にhandle_responseを指定。ここにアクセスしたレスポンスが入る
                client.fetch(req, handle_response)
            except tornado.httpclient.HTTPError as e:
                if hasattr(e, 'response') and e.response:
                    handle_response(e.response)
                else:
                    self.set_status(500)
                    self.write('Internal server error:\n' + str(e))
                    self.finish()

    @tornado.web.asynchronous
    def post(self):
         #POSTリクエストもGETメソッド内で一括処理
        return self.get()

def run_proxy(port):
    app = tornado.web.Application([
        (r'.*', ProxyHandler),
    ])
    app.listen(port)
    tornado.ioloop.IOLoop.instance().start() #プロキシサーバを稼働させる

if __name__ == '__main__':
    port = 8888
    if len(sys.argv) > 1:
        port = int(sys.argv[1])

    print ("Starting cache proxy on port %d" % port)
    run_proxy(port)