// Geometry audit against rendered modules, not snapshots of CSS source strings.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';

export async function auditWorkbenchLayout(page,out,{strict=true}={}) {
    const workbench=page.locator('.hutx-workbench'),reports=[];
    await workbench.getByRole('tab',{name:/角色与声音/}).click();
    await workbench.getByRole('textbox',{name:'角色 A 名称',exact:true}).fill('Alexandra — 角色名称较长的版面检查');
    await workbench.locator('[data-role=C] [data-field=mode]').selectOption('clone');
    await workbench.locator('[data-role=C] [data-field=reference_file]').evaluate(input=>{input.value='测试参考声线_very-long-reference-recording-name.wav';input.dispatchEvent(new Event('input',{bubbles:true}));});
    await page.evaluate(()=>{
        const state=app.graph.extra.hutx_workbench;
        state.shots[0].title='LongShotTitleWithoutSpaces'.repeat(4);
        state.shortlist[0].title='LongVideoFilenameWithoutSpaces'.repeat(4);
    });
    async function inspect(name){
        const report=await workbench.evaluate(root=>{
            const box=root.getBoundingClientRect(),content=root.querySelector('.wb-content'),bounds=content.getBoundingClientRect();
            const visible=node=>node.getClientRects().length&&getComputedStyle(node).visibility!=='hidden';
            const outside=[...root.querySelectorAll('button,input,select,textarea')].filter(visible).filter(node=>{
                if(node.closest('.wb-content')!==content)return false;
                const r=node.getBoundingClientRect();return r.left<bounds.left-1||r.right>bounds.right+1;
            }).map(node=>({tag:node.tagName,label:node.getAttribute('aria-label')||node.textContent?.slice(0,55),width:node.getBoundingClientRect().width}));
            const cards=[...root.querySelectorAll('.hutx-role')].filter(visible).map(node=>{
                const r=node.getBoundingClientRect(),summary=node.querySelector('summary').getBoundingClientRect();
                const text=node.querySelector('[data-field=text]');
                const actionTop=[node.querySelector('[data-field=speed]'),...node.querySelectorAll('.hutx-speech-action-controls>button')].filter(visible).filter(item=>item.type==='number'||/生成|采用/.test(item.textContent)).map(item=>item.getBoundingClientRect().top);
                return {left:r.left,top:r.top,width:r.width,summary:summary.height,overflow:node.scrollWidth-node.clientWidth,textTop:text?.getBoundingClientRect().top,actionTop};
            });
            const tabs=[...root.querySelectorAll('.wb-tabs button')].map(node=>node.getBoundingClientRect().width);
            const align=[...root.querySelectorAll('.wb-project,.wb-tabs,.wb-content')].map(node=>{const r=node.getBoundingClientRect(),style=getComputedStyle(node);return r.left+parseFloat(style.paddingLeft);});
            const fields=[...root.querySelectorAll('.wb-clip-fields input[type=number]')].slice(0,3).map(node=>{const r=node.getBoundingClientRect();return {width:r.width,top:r.top};});
            const refinement=root.querySelector('.wb-refinements'),run=root.querySelector('.wb-bottom [data-action=generate]');
            const refinementLayout=refinement&&visible(refinement)&&run&&visible(run)?(()=>{
                const r=refinement.getBoundingClientRect(),b=run.getBoundingClientRect();
                return {centerError:Math.abs((r.left+r.right-b.left-b.right)/2),above:r.bottom<=b.top,overflow:refinement.scrollWidth-refinement.clientWidth,left:r.left,right:r.right};
            })():null;
            return {width:box.width,overflow:content.scrollWidth-content.clientWidth,outside,cards,tabs,align,fields,refinementLayout,
                shellOverflow:Math.max(0,box.right-window.innerWidth,-box.left),footer:root.querySelector('.wb-bottom').getBoundingClientRect().height};
        });
        reports.push({name,...report});
        if(strict){
            assert(report.overflow<=1,`${name}: horizontal content overflow ${report.overflow}`);
            assert(report.shellOverflow<=1,`${name}: shell outside viewport`);
            if(report.refinementLayout){
                assert(report.refinementLayout.centerError<=1,`${name}: refinements not centered over run button`);
                assert(report.refinementLayout.above,`${name}: refinements below run button`);
                assert(report.refinementLayout.overflow<=1,`${name}: refinement controls clipped`);
            }
            assert.deepEqual(report.outside,[],`${name}: controls clipped horizontally`);
            assert(Math.max(...report.tabs)-Math.min(...report.tabs)<1,`${name}: unequal tabs`);
            assert(Math.max(...report.align)-Math.min(...report.align)<1,`${name}: page gutters misaligned`);
            for(const card of report.cards)assert(card.overflow<=1,`${name}: clipped role card`);
            for(const card of report.cards)if(card.width>=330&&card.actionTop.length)assert(Math.max(...card.actionTop)-Math.min(...card.actionTop)<8,`${name}: speech controls wrap in a full-size card`);
            if(report.cards.length===3&&Math.abs(report.cards[0].top-report.cards[1].top)<1){
                assert(Math.max(...report.cards.map(card=>card.width))-Math.min(...report.cards.map(card=>card.width))<1,`${name}: unequal role widths`);
                assert(Math.abs((report.cards[1].left-report.cards[0].left-report.cards[0].width)-(report.cards[2].left-report.cards[1].left-report.cards[1].width))<1,`${name}: unequal role gaps`);
                assert(Math.max(...report.cards.map(card=>card.textTop))-Math.min(...report.cards.map(card=>card.textTop))<1,`${name}: preset and clone dialogue fields are misaligned`);
            }
            for(const field of report.fields){const row=report.fields.filter(item=>Math.abs(item.top-field.top)<1);assert(Math.max(...row.map(item=>item.width))-Math.min(...row.map(item=>item.width))<1,`${name}: unequal clip inputs on the same row`);}
        }
    }
    await page.setViewportSize({width:1600,height:900});
    for(const width of [280,320,360,540,900,1100]){
        await page.locator('#sidebar').evaluate((node,width)=>node.style.width=width+'px',width);
        for(const [key,title] of [['roles','角色与声音'],['generate','镜头生成'],['results','成片管理']]){
            await workbench.getByRole('tab',{name:new RegExp(title)}).click();
            if(key==='results')await workbench.locator('.wb-clip').first().evaluate(node=>node.open=true);
            await inspect(`sidebar-${width}-${key}`);
        }
    }
    await workbench.getByRole('button',{name:'展开',exact:true}).click();
    for(const size of [{width:1920,height:1080},{width:1280,height:720},{width:800,height:600},{width:390,height:844}]){
        await page.setViewportSize(size);
        for(const [key,title] of [['roles','角色与声音'],['generate','镜头生成'],['results','成片管理']]){
            await workbench.getByRole('tab',{name:new RegExp(title)}).click();
            if(key==='results')await workbench.locator('.wb-clip').first().evaluate(node=>node.open=true);
            await inspect(`expanded-${size.width}-${key}`);
            if(size.width===1280||size.width===390){
                await workbench.locator('.wb-content').evaluate(node=>node.scrollTop=0);
                await workbench.screenshot({path:path.join(out,`layout-${size.width}-${key}.png`)});
                if(key==='roles'&&size.width===1280){await workbench.locator('.hutx-multi-cards').evaluate(node=>node.scrollIntoView({block:'start'}));await workbench.screenshot({path:path.join(out,'layout-role-cards.png')});}
                if(key==='results'&&size.width===390){await workbench.locator('.wb-clip-fields').first().evaluate(node=>node.scrollIntoView({block:'center'}));await workbench.screenshot({path:path.join(out,'layout-clip-controls.png')});}
            }
        }
    }
    await page.setViewportSize({width:390,height:520});
    await page.evaluate(()=>{
        testEvents.dispatchEvent(new CustomEvent('execution_start',{detail:{prompt_id:'layout-error'}}));
        testEvents.dispatchEvent(new CustomEvent('execution_error',{detail:{prompt_id:'layout-error',exception_message:'较长错误说明，检查状态栏是否挤压主界面。'.repeat(30)}}));
    });
    const statusLayout=await workbench.evaluate(root=>({footer:root.querySelector('.wb-bottom').getBoundingClientRect().height,content:root.querySelector('.wb-content').clientHeight}));
    assert(statusLayout.footer<90&&statusLayout.content>100,'long error status displaces the editor');
    await page.setViewportSize({width:1440,height:1100});
    await workbench.getByRole('button',{name:'收起',exact:true}).click();
    await page.locator('#sidebar').evaluate(node=>node.style.width='360px');
    fs.writeFileSync(path.join(out,'layout-audit.json'),JSON.stringify(reports,null,2));
    return reports;
}
