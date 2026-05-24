module pcie_iip_rams (

);

ram_2p_1c_wrapper #(
	.RD_LATENCY(1)
	.WD(2)，
	.PW(3)，
	.DP (7)
) u_ib_mcpl_sb_ram [2-1:0] (
	.clk     (), //input
	.addra (), //input
	.addrb(), //input
	.dina(), //input
	.doutb(), //output
	.ena(), //input
	.enb(), //input
	.wea () //input
);

ram_2p_2c_wrapper #(
	.RD_LATENCY(1)
	.WD(2)，
	.PW(3)，
	.DP (7)
) u_ib_mcpl_sb_ram1  (
	.clka     (), //input
	.clkb     (), //input
	.addra (), //input
	.addrb(), //input
	.dina(), //input
	.doutb(), //output
	.ena(), //input
	.enb(), //input
	.wea () //input
);

ram_1p_wrapper #(
	.RD_LATENCY(1)
	.WD(2)，
	.PW(3)，
	.DP (7)
) u_ib_mcpl_sb1_ram1  (
	.clk     (), //input
	.addr (), //input
	.din(), //input
	.dout(), //output
	.en(), //input
	.we () //input
);

ram_1p_be_wrapper #(
	.RD_LATENCY(1)
	.WEW (3),
	.WD(2)，
	.PW(3)，
	.DP (7)
) u_ib_mcpl_sb1_ram31  (
	.clk     (), //input
	.addr (), //input
	.din(), //input
	.dout(), //output
	.en(), //input
	.we () //input
);
endmodule