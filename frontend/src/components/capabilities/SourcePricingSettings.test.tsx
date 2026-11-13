// @vitest-environment jsdom
import {useState} from 'react'
import {cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react'
import {App} from 'antd'
import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {api} from '../../api'
import SourcePricingSettings,{type SourcePriceDraft} from './SourcePricingSettings'
vi.mock('../../api',()=>({api:vi.fn()}))
vi.mock('../../i18n',()=>({useI18n:()=>({t:(key:string)=>key,locale:'en-US'})}))
vi.mock('../../layout',()=>({useLayout:()=>({phone:false})}))
const rule=(input:number)=>({mode:'tokens' as const,price:{input_per_million:input,output_per_million:30,cache_read_per_million:1}})
function Harness(){const[draft,setDraft]=useState<SourcePriceDraft>();return <App><SourcePricingSettings sourceId="a" models={['gpt-5']} draft={draft} onChange={setDraft}/></App>}
beforeEach(()=>{
 window.matchMedia=vi.fn().mockImplementation(()=>({matches:false,addListener:vi.fn(),removeListener:vi.fn(),addEventListener:vi.fn(),removeEventListener:vi.fn()}))
 let saved={default:rule(3),models:{'gpt-5':rule(10)},multiplier:2,accountStrategy:'smart'}
 const snapshot=()=>({data:structuredClone(saved),currency:'CNY',effective:[{model:'gpt-5',origin:'model',rule:saved.models['gpt-5'],price:{...saved.models['gpt-5'].price,input_per_million:saved.models['gpt-5'].price.input_per_million*2},known:true,multiplier:2}],summary:{model:'',origin:'source',rule:saved.default,price:saved.default.price,known:true,multiplier:2}})
 vi.mocked(api).mockImplementation(async(method,path,body)=>{if(method==='PUT'){if(path.includes('scope=model'))saved={...saved,models:body.models};else saved={...saved,default:body.default,multiplier:body.multiplier}}return snapshot()})
})
afterEach(()=>{cleanup();vi.clearAllMocks()})
it('saves one model without committing source drafts and saves defaults without committing model drafts',async()=>{
 const {container}=render(<Harness/>)
 const source=await screen.findByText('pricing.default',{selector:'h3'}).then(element=>element.closest('section')!)
 fireEvent.change(within(source).getByLabelText('pricing.input'),{target:{value:'8'}})
 fireEvent.click(screen.getByRole('button',{name:'pricing.editModel'}))
 let editor=container.querySelector('.source-price-inspector')!
 fireEvent.change(within(editor as HTMLElement).getByLabelText('pricing.input'),{target:{value:'12'}})
 fireEvent.click(within(editor as HTMLElement).getByRole('button',{name:'pricing.save'}))
 await waitFor(()=>expect(container.querySelector('.source-price-inspector')).toBeNull())
 expect(api).toHaveBeenCalledWith('PUT','/agent/model-gateway/settings/sources/a?scope=model&model=gpt-5',expect.objectContaining({default:rule(3),models:{'gpt-5':{...rule(12),confirmed:false}}}))
 expect((within(source).getByLabelText('pricing.input') as HTMLInputElement).value).toBe('8')
 expect(container.querySelector('td[data-label="pricing.input"]')?.textContent).toBe('24')
 fireEvent.click(screen.getByRole('button',{name:'pricing.editModel'}))
 editor=container.querySelector('.source-price-inspector')!
 fireEvent.change(within(editor as HTMLElement).getByLabelText('pricing.input'),{target:{value:'20'}})
 fireEvent.click(within(editor as HTMLElement).getByRole('button',{name:'common.back'}))
 fireEvent.click(within(source).getByRole('button',{name:'pricing.save'}))
 await waitFor(()=>expect(api).toHaveBeenCalledWith('PUT','/agent/model-gateway/settings/sources/a?scope=default',expect.objectContaining({default:{...rule(8),confirmed:false},models:{'gpt-5':{...rule(12),confirmed:false}}})))
 fireEvent.click(screen.getByRole('button',{name:'pricing.editModel'}))
 editor=container.querySelector('.source-price-inspector')!
 expect((within(editor as HTMLElement).getByLabelText('pricing.input') as HTMLInputElement).value).toBe('20')
})
it('requires free confirmation and rejects invalid numeric prices without sending writes',async()=>{
 const {container}=render(<Harness/>)
 fireEvent.click(await screen.findByRole('button',{name:'pricing.editModel'}))
 const editor=container.querySelector('.source-price-inspector')! as HTMLElement
 fireEvent.change(within(editor).getByLabelText('pricing.input'),{target:{value:'-1'}})
 expect((within(editor).getByRole('button',{name:'pricing.save'}) as HTMLButtonElement).disabled).toBe(true)
 fireEvent.mouseDown(within(editor).getByRole('combobox',{name:'pricing.method'}))
 fireEvent.click(await screen.findByText('pricing.free',{selector:'.ant-select-item-option-content'}))
 expect((within(editor).getByRole('button',{name:'pricing.save'}) as HTMLButtonElement).disabled).toBe(true)
 fireEvent.click(within(editor).getByRole('checkbox',{name:'pricing.confirm'}))
 expect((within(editor).getByRole('button',{name:'pricing.save'}) as HTMLButtonElement).disabled).toBe(false)
 expect(vi.mocked(api).mock.calls.filter(([method])=>method==='PUT')).toHaveLength(0)
})
