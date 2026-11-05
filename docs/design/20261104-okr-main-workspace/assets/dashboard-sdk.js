(() => {
  const bootstrap = window.__okrDashboardBootstrap;
  let port;
  let nextId = 0;
  const pending = new Map();
  const subscriptions = new Map();
  const outbox = [];
  const send = message => port ? port.postMessage(message) : outbox.push(message);
  window.okr = Object.freeze({data:Object.freeze({
    read(dataset) {
      const id = String(++nextId);
      return new Promise((resolve,reject) => {
        pending.set(id,{resolve,reject});
        send({type:'read',id,dataset});
      });
    },
    subscribe(dataset,callback) {
      const handlers = subscriptions.get(dataset) || new Set();
      handlers.add(callback);subscriptions.set(dataset,handlers);
      send({type:'subscribe',dataset});
      return () => {handlers.delete(callback);if(!handlers.size){subscriptions.delete(dataset);send({type:'unsubscribe',dataset});}};
    }
  })});
  window.addEventListener('message', event => {
    if(port || event.source!==parent || event.origin!==bootstrap.origin || event.data?.type!=='okr:channel' || event.data?.nonce!==bootstrap.nonce || !event.ports[0]) return;
    port=event.ports[0];
    port.onmessage=event=>{
      const message=event.data;
      if(message.type==='result'){
        const request=pending.get(message.id);if(!request)return;pending.delete(message.id);
        message.error?request.reject(new Error(message.error)):request.resolve(message.data);
      }
      if(message.type==='update') for(const handler of subscriptions.get(message.dataset)||[])handler(message.data);
    };
    port.start();outbox.splice(0).forEach(message=>port.postMessage(message));
  });
  parent.postMessage({type:'okr:ready',nonce:bootstrap.nonce},bootstrap.origin);
  window.addEventListener('pagehide',()=>{port?.close();for(const request of pending.values())request.reject(new Error('DASHBOARD_CLOSED'));pending.clear();subscriptions.clear();});
})();
