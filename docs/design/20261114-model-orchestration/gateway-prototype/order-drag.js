export function bindOrderDrag(orderList, orderPane, bind, moveDraftMember) {
  let drag = null
  function locateDraftDrop() {
    const list=orderList.getBoundingClientRect()
    const pane=orderPane.getBoundingClientRect()
    let target=drag.from
    if (drag.x>=list.left && drag.x<=list.right && drag.y>=Math.max(list.top,pane.top) && drag.y<=Math.min(list.bottom,pane.bottom)) {
      let distance=Infinity
      drag.items.forEach((item,index)=>{
        const rect=item.getBoundingClientRect()
        const gap=Math.abs(drag.y-(rect.top+rect.height/2))
        if (gap<distance) { target=index; distance=gap }
      })
    }
    if (target===drag.to) return
    drag.items[drag.to].classList.remove('is-drop-before','is-drop-after')
    if (target!==drag.from) drag.items[target].classList.add(target<drag.from?'is-drop-before':'is-drop-after')
    drag.to=target
  }
  function scrollDraftList() {
    const bounds=orderPane.getBoundingClientRect()
    const edge=drag.grip.offsetHeight
    if (drag.x>=bounds.left && drag.x<=bounds.right) {
      const distance=drag.y<bounds.top+edge?drag.y-bounds.top-edge:Math.max(0,drag.y-bounds.bottom+edge)
      orderPane.scrollTop+=Math.max(-edge/3,Math.min(edge/3,distance/4))
    }
    locateDraftDrop()
    drag.frame=requestAnimationFrame(scrollDraftList)
  }
  function cancelDraftDrag() {
    if (!drag) return
    const {grip,pointer,from,to,items,frame}=drag
    drag=null
    cancelAnimationFrame(frame)
    items[from].classList.remove('is-dragging')
    items[to].classList.remove('is-drop-before','is-drop-after')
    if (grip.hasPointerCapture(pointer)) grip.releasePointerCapture(pointer)
  }
  bind(orderList, 'pointerdown',event=>{
    const grip=event.target.closest('.order-grip')
    if (!grip || event.button!==0 || !event.isPrimary || drag) return
    event.preventDefault()
    const from=Number(grip.dataset.orderIndex)
    grip.focus({preventScroll:true})
    grip.setPointerCapture(event.pointerId)
    drag={grip,pointer:event.pointerId,from,to:from,items:[...orderList.children],x:event.clientX,y:event.clientY,startY:event.clientY,frame:null}
  })
  bind(document, 'pointermove',event=>{
    if (!drag || event.pointerId!==drag.pointer) return
    drag.x=event.clientX
    drag.y=event.clientY
    if (drag.frame===null) {
      if (Math.abs(drag.y-drag.startY)<6) return
      drag.items[drag.from].classList.add('is-dragging')
      drag.frame=requestAnimationFrame(scrollDraftList)
    }
    event.preventDefault()
    locateDraftDrop()
  })
  bind(document, 'pointerup',event=>{
    if (!drag || event.pointerId!==drag.pointer) return
    if (drag.frame!==null) {
      drag.x=event.clientX
      drag.y=event.clientY
      locateDraftDrop()
    }
    const {from,to}=drag
    cancelDraftDrag()
    moveDraftMember(from,to)
  })
  for (const type of ['pointercancel','lostpointercapture']) bind(document, type,event=>{
    if (drag?.pointer===event.pointerId) cancelDraftDrag()
  })
  bind(window, 'blur',cancelDraftDrag)
  bind(orderList, 'keydown',event=>{
    const grip=event.target.closest('.order-grip')
    if (!grip) return
    if (event.key==='Escape') { cancelDraftDrag(); return }
    if (drag) return
    const from=Number(grip.dataset.orderIndex)
    const target={ArrowUp:from-1,ArrowDown:from+1,Home:0,End:orderList.children.length-1}[event.key]
    if (target===undefined) return
    event.preventDefault()
    moveDraftMember(from,target)
  })
  return cancelDraftDrag
}
