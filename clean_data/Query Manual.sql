update product_template set website_id=null where website_id in (select id from website where company_id=10);
delete from product_public_category where website_id in (select id from website where company_id=10);
delete from payment_acquirer where company_id=10;
delete from website where company_id=10;
delete from res_users where company_id=10;
delete from account_partial_reconcile 
                where debit_move_id in (select id from account_move_line 
                    where move_id in (select account_move.id from account_move where company_id=10 ));
delete from account_partial_reconcile where credit_move_id in (select id from account_move_line 
                where move_id in (select account_move.id from account_move where company_id=10 ));
delete from account_move_line where move_id in (select account_move.id from account_move 
                 where company_id=10 );
delete from account_move where id in (select account_move.id from account_move 
                 where company_id=10 );
delete from stock_quant 
                               where company_id=10;
delete from stock_move_line 
                               where company_id=10;
delete from stock_move 
                               where company_id=10;
delete from stock_picking_type 
                               where company_id=10;
delete from stock_picking 
                               where company_id=10;

delete from stock_quant where company_id=10;
delete from stock_move_line where company_id=10;
delete from stock_move where company_id=10;
delete from stock_picking where company_id=10;
delete from account_partial_reconcile where company_id=10;
delete from account_payment_register where company_id=10;
delete from account_move_line where company_id=10;
delete from account_move where company_id=10;
delete from sale_order_line where company_id=10;
delete from sale_order where company_id=10;

delete from account_payment where id in (select account_payment.id from account_payment join account_move on account_move.id = account_payment.move_id where account_move.company_id=10);

delete from account_transfer_model_line where id in (select account_transfer_model_line.id from account_transfer_model_line 
                                     join account_transfer_model 
                                       on account_transfer_model.id = account_transfer_model_line.transfer_model_id 
                                     join account_journal 
                                       on account_journal.id = account_transfer_model.journal_id
                              where account_journal.company_id=10); 

delete from account_transfer_model where id in (select account_transfer_model.id from account_transfer_model 
                                     join account_journal 
                                       on account_journal.id = account_transfer_model.journal_id
                              where account_journal.company_id=10);


delete from stock_quant where company_id=10;
delete from stock_move_line where company_id=10;
delete from stock_move where company_id=10;
delete from stock_picking where company_id=10;
delete from account_partial_reconcile where company_id=10;
delete from account_payment_register where company_id=10;
delete from account_move_line where company_id=10;
delete from account_move where company_id=10;
delete from purchase_order where company_id=10;
delete from purchase_order_line where company_id=10;

delete from stock_picking where company_id=10;
delete from stock_move_line where company_id=10;
delete from stock_move where company_id=10;
delete from stock_quant where company_id=10;

delete from account_partial_reconcile where company_id=10;
delete from account_payment_register where company_id=10;
delete from account_move_line where company_id=10;
delete from account_move where company_id=10;

delete from res_partner where id not in (select partner_id from res_users union select partner_id 
    from res_company) and company_id=10;

delete from account_fiscal_position where company_id=10;
delete from purchase_requisition where company_id=10;
delete from stock_rule where company_id=10;
delete from stock_picking_type where company_id=10;
delete from stock_valuation_layer where company_id=10;
delete from stock_warehouse where company_id=10;
delete from account_followup_followup_line where company_id=10;
delete from account_reconcile_model where company_id=10;
delete from ir_property where company_id=10;

delete from product_template where company_id=10;
delete from product_product where company_id=10;
delete from pos_payment_method where journal_id in (select id from account_journal where company_id=10);
delete from account_journal where company_id=10;
delete from account_account where company_id=10;
delete from account_tax where company_id=10;